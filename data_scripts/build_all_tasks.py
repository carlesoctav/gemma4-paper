#!/usr/bin/env python3
"""Build Docker images for Harbor benchmark tasks in parallel and update task.toml."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def detect_runtime() -> str:
    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    raise RuntimeError("Neither 'podman' nor 'docker' executable found in PATH.")


def image_exists(runtime: str, tag: str) -> bool:
    cmd = [runtime, "image", "exists", tag] if runtime == "podman" else [runtime, "image", "inspect", tag]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def update_task_toml_content(content: str, image_tag: str) -> str:
    # Check if docker_image is already defined
    if re.search(r"^\s*docker_image\s*=", content, flags=re.MULTILINE):
        return re.sub(
            r"^\s*docker_image\s*=.*$",
            f'docker_image = "{image_tag}"',
            content,
            flags=re.MULTILINE,
        )
    # If [environment] exists, add docker_image beneath it
    if re.search(r"^\s*\[environment\]\s*$", content, flags=re.MULTILINE):
        return re.sub(
            r"^\s*\[environment\]\s*$",
            f'[environment]\ndocker_image = "{image_tag}"',
            content,
            flags=re.MULTILINE,
        )
    # Otherwise append [environment] block
    return content.rstrip() + f'\n\n[environment]\ndocker_image = "{image_tag}"\n'


def copy_or_link_task(src_task_dir: Path, dst_task_dir: Path, link_mode: str) -> None:
    if dst_task_dir.resolve() == src_task_dir.resolve():
        return
    if dst_task_dir.exists():
        return

    dst_task_dir.mkdir(parents=True, exist_ok=True)
    for item in src_task_dir.iterdir():
        dst_item = dst_task_dir / item.name
        if item.is_dir():
            if link_mode == "symlink":
                dst_item.symlink_to(item.resolve())
            elif link_mode == "hardlink":
                shutil.copytree(item, dst_item, copy_function=os.link)
            else:
                shutil.copytree(item, dst_item)
        else:
            if link_mode == "symlink" and item.name != "task.toml":
                dst_item.symlink_to(item.resolve())
            elif link_mode == "hardlink" and item.name != "task.toml":
                os.link(item, dst_item)
            else:
                shutil.copy2(item, dst_item)


def find_dockerfile_and_context(task_dir: Path) -> tuple[Path, Path] | None:
    if (task_dir / "environment" / "Dockerfile").is_file():
        return task_dir / "environment", task_dir / "environment" / "Dockerfile"
    if (task_dir / "Dockerfile").is_file():
        return task_dir, task_dir / "Dockerfile"
    return None


def build_and_register_task(
    task_dir: Path,
    out_task_dir: Path,
    runtime: str,
    tag_prefix: str,
    push_to: str | None,
    force: bool,
    link_mode: str,
) -> tuple[str, str, float]:
    task_id = task_dir.name
    target_tag = f"{push_to}:{task_id}" if push_to else f"{tag_prefix}:{task_id}"

    t0 = time.time()
    skipped = False

    docker_ctx = find_dockerfile_and_context(task_dir)
    if docker_ctx is not None:
        context_dir, dockerfile_path = docker_ctx
        if not force and image_exists(runtime, target_tag):
            skipped = True
        else:
            build_cmd = [runtime, "build", "-t", target_tag, "-f", str(dockerfile_path), str(context_dir)]
            proc = subprocess.run(build_cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                err_msg = (proc.stderr or proc.stdout)[-1000:]
                raise RuntimeError(f"Build failed for {task_id} (tag: {target_tag}):\n{err_msg}")

            if push_to:
                push_cmd = [runtime, "push", target_tag]
                proc = subprocess.run(push_cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    err_msg = (proc.stderr or proc.stdout)[-1000:]
                    raise RuntimeError(f"Push failed for {task_id} (tag: {target_tag}):\n{err_msg}")
    else:
        skipped = True

    # Prepare output task directory
    copy_or_link_task(task_dir, out_task_dir, link_mode)

    # Update task.toml in out_task_dir
    src_toml_path = task_dir / "task.toml"
    dst_toml_path = out_task_dir / "task.toml"

    if src_toml_path.is_file():
        content = src_toml_path.read_text(encoding="utf-8")
        if docker_ctx is not None:
            new_content = update_task_toml_content(content, target_tag)
        else:
            new_content = content
        dst_toml_path.write_text(new_content, encoding="utf-8")

    duration = time.time() - t0
    if docker_ctx is None:
        status = "PASSTHRU"
    elif skipped:
        status = "EXISTS"
    else:
        status = "BUILT"
    return task_id, status, duration


def main() -> None:
    parser = argparse.ArgumentParser(description="Build task Docker images in parallel and update task.toml")
    parser.add_argument("tasks_dir", type=Path, help="Directory containing task subdirectories")
    parser.add_argument("out_dir", type=Path, nargs="?", default=None, help="Output tasks directory (default: <tasks_dir>_build)")
    parser.add_argument("-j", "--num-workers", type=int, default=os.cpu_count() or 4, help="Number of worker threads")
    parser.add_argument("--out-dir", type=Path, default=None, dest="out_dir_flag", help="Output tasks directory (default: <tasks_dir>_build)")
    parser.add_argument("--in-place", action="store_true", help="Modify tasks directory in-place instead of creating <tasks_dir>_build")
    parser.add_argument("--tag-prefix", type=str, default=None, help="Prefix for image tags (default: tasks_dir name)")
    parser.add_argument("--push-to", type=str, default=None, help="Remote repository prefix (e.g. quay.io/carlesoctav/termgrade)")
    parser.add_argument("--runtime", type=str, default=None, choices=["docker", "podman"], help="Container runtime")
    parser.add_argument("--force", action="store_true", help="Force rebuild even if image already exists")
    parser.add_argument("--link-mode", type=str, default="copy", choices=["copy", "symlink", "hardlink"], help="Mode for creating out-dir")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of tasks to process")
    args = parser.parse_args()

    tasks_dir = args.tasks_dir.resolve()
    out_target = args.out_dir_flag or args.out_dir
    if out_target is not None:
        out_dir = out_target.resolve()
    elif args.in_place:
        out_dir = tasks_dir
    else:
        out_dir = tasks_dir.parent / f"{tasks_dir.name}_build"

    tag_prefix = args.tag_prefix or tasks_dir.name
    runtime = args.runtime or detect_runtime()

    print(f"=== Harbor Task Docker Builder ===", flush=True)
    print(f"Tasks Source: {tasks_dir}", flush=True)
    print(f"Tasks Output: {out_dir}", flush=True)
    print(f"Workers:      {args.num_workers}", flush=True)
    print(f"Runtime:      {runtime}", flush=True)
    print(f"Tag Prefix:   {tag_prefix}", flush=True)
    if args.push_to:
        print(f"Pushing to:   {args.push_to}", flush=True)

    # Discover tasks
    def is_task_dir(d: Path) -> bool:
        if not d.is_dir():
            return False
        return (
            (d / "task.toml").is_file()
            or (d / "environment" / "Dockerfile").is_file()
            or (d / "Dockerfile").is_file()
            or (d / "environment" / "docker-compose.yaml").is_file()
        )

    task_dirs = sorted([d for d in tasks_dir.iterdir() if is_task_dir(d)])

    if args.limit:
        task_dirs = task_dirs[:args.limit]

    total = len(task_dirs)
    print(f"Found {total} tasks to process.\n", flush=True)

    if total == 0:
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    completed = 0
    built_count = 0
    exists_count = 0
    start_all = time.time()

    with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
        futures = {
            executor.submit(
                build_and_register_task,
                tdir,
                out_dir / tdir.name,
                runtime,
                tag_prefix,
                args.push_to,
                args.force,
                args.link_mode,
            ): tdir
            for tdir in task_dirs
        }

        for fut in as_completed(futures):
            completed += 1
            task_id, status, dur = fut.result()
            if status == "BUILT":
                built_count += 1
            elif status == "EXISTS":
                exists_count += 1

            pct = completed / total * 100
            print(f"[{completed}/{total}] ({pct:5.1f}%) [{status:8s}] {task_id} ({dur:.2f}s)", flush=True)

    total_time = time.time() - start_all
    print(f"\nFinished in {total_time:.2f}s ({built_count} built, {exists_count} already existed).", flush=True)


if __name__ == "__main__":
    main()
