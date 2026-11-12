import matplotlib.pyplot as plt
import os

os.makedirs("paper/figures", exist_ok=True)
plt.style.use(
    "seaborn-v0_8-whitegrid"
    if "seaborn-v0_8-whitegrid" in plt.style.available
    else "default"
)


def plot_base_it(ax):
    ax.plot(
        [0.00, 0.04],
        [0.2703, 0.2703],
        color="black",
        linewidth=3.5,
        zorder=5,
        label="Base IT (new: 0.00–0.04, old: 0.2703)",
    )
    ax.scatter(
        [0.00, 0.04],
        [0.2703, 0.2703],
        color="black",
        s=90,
        marker="|",
        linewidths=2.5,
        zorder=6,
    )
    ax.axvspan(0.00, 0.04, color="gray", alpha=0.14)


# Trajectories from benchmark table
lora_1e4_x = [0.0404, 0.0900, 0.1010]
lora_1e4_y = [0.2005, 0.1920, 0.1722]

lora_1e5_x = [0.0500, 0.0400, 0.0400]
lora_1e5_y = [0.3038, 0.3294, 0.2690]

graft_1e4_x = [0.0300, 0.0600, 0.0300]
graft_1e4_y = [0.2868, 0.2565, 0.2827]

graft_1e5_x = [0.0500, 0.0100, 0.0300]
graft_1e5_y = [0.3176, 0.2751, 0.2788]


# 1. LoRA vs Grafting
fig, ax = plt.subplots(figsize=(7.5, 5.2))
plot_base_it(ax)

ax.plot(
    lora_1e4_x,
    lora_1e4_y,
    "o-",
    color="#d95f02",
    linewidth=2.5,
    markersize=8,
    label="Simple LoRA (lr=1e-4)",
)
for i, txt in enumerate(["ckpt-50", "ckpt-75", "step-100"]):
    ax.annotate(
        f" {txt}",
        (lora_1e4_x[i], lora_1e4_y[i]),
        fontsize=9,
        fontweight="bold",
        color="#d95f02",
    )

ax.plot(
    lora_1e5_x,
    lora_1e5_y,
    "s--",
    color="#7570b3",
    linewidth=2,
    markersize=7,
    label="Simple LoRA (lr=1e-5)",
)

ax.plot(
    graft_1e4_x,
    graft_1e4_y,
    "^--",
    color="#1b9e77",
    linewidth=2.5,
    markersize=8,
    label="Grafting Base->IT (lr=1e-4)",
)
for i, txt in enumerate(["ckpt-50", "ckpt-75", "step-100"]):
    offset = (0, 6) if i == 0 else (0, -11) if i == 2 else (4, -3)
    ax.annotate(
        txt,
        (graft_1e4_x[i], graft_1e4_y[i]),
        xytext=offset,
        textcoords="offset points",
        fontsize=8.5,
        color="#1b9e77",
    )

ax.plot(
    graft_1e5_x,
    graft_1e5_y,
    "v:",
    color="#66a61e",
    linewidth=2,
    markersize=7,
    label="Grafting Base->IT (lr=1e-5)",
)

ax.set_xlabel("New Task: termgrade-100 (Reward @ 1)", fontsize=12, fontweight="bold")
ax.set_ylabel("Old Task: gemma4_gh_pr (Reward @ 1)", fontsize=12, fontweight="bold")
ax.set_title("Run: LoRA vs Grafting Trajectory", fontsize=14, fontweight="bold")
ax.legend(frameon=True, loc="upper right", fontsize=9.5)
ax.set_xlim(-0.005, 0.125)
ax.set_ylim(0.11, 0.345)
plt.tight_layout()
plt.savefig("paper/figures/lora_vs_grafting.png", dpi=300)
plt.close()


# 2. LoRA vs OPLoRA / Subspace Tuning
fig, ax = plt.subplots(figsize=(7.5, 5.2))
plot_base_it(ax)

ax.plot(
    lora_1e4_x,
    lora_1e4_y,
    "o-",
    color="#d95f02",
    linewidth=2.5,
    markersize=8,
    label="Simple LoRA (lr=1e-4)",
)
for i, txt in enumerate(["ckpt-50", "ckpt-75", "step-100"]):
    ax.annotate(
        f" {txt}",
        (lora_1e4_x[i], lora_1e4_y[i]),
        fontsize=9,
        fontweight="bold",
        color="#d95f02",
    )

ax.scatter(
    [0.0909],
    [0.1782],
    color="#e7298a",
    s=130,
    marker="D",
    zorder=5,
    label="oplora-k-128 (0.0909 / 0.1782)",
)
ax.annotate(
    "oplora-k-128",
    (0.0909, 0.1782),
    xytext=(-78, -6),
    textcoords="offset points",
    fontsize=9.5,
    fontweight="bold",
    color="#e7298a",
)

ax.scatter(
    [0.0600],
    [0.1268],
    color="#e6ab02",
    s=140,
    marker="X",
    zorder=5,
    label="oplora-r90 pre-Adam (0.0600 / 0.1268)",
)
ax.annotate(
    " oplora-r90 (pre-Adam)",
    (0.0600, 0.1268),
    fontsize=9.5,
    fontweight="bold",
    color="#b8860b",
)

ax.scatter(
    [0.0400],
    [0.1950],
    color="#2b83ba",
    s=150,
    marker="P",
    zorder=5,
    label="oplora-v2-r90 post-Adam (0.0400 / 0.1950)",
)
ax.annotate(
    "oplora-v2-r90 (post-Adam)",
    (0.0400, 0.1950),
    xytext=(-15, -16),
    textcoords="offset points",
    fontsize=9.5,
    fontweight="bold",
    color="#2b83ba",
)

ax.set_xlabel("New Task: termgrade-100 (Reward @ 1)", fontsize=12, fontweight="bold")
ax.set_ylabel("Old Task: gemma4_gh_pr (Reward @ 1)", fontsize=12, fontweight="bold")
ax.set_title("Run: LoRA vs Subspace Tuning / OPLoRA", fontsize=14, fontweight="bold")
ax.legend(frameon=True, loc="upper right", fontsize=9.5)
ax.set_xlim(-0.005, 0.125)
ax.set_ylim(0.11, 0.345)
plt.tight_layout()
plt.savefig("paper/figures/lora_vs_oplora.png", dpi=300)
plt.close()


# 3. All Methods Combined
fig, ax = plt.subplots(figsize=(8, 5.5))
plot_base_it(ax)

ax.plot(
    lora_1e4_x,
    lora_1e4_y,
    "o-",
    color="#d95f02",
    linewidth=2.5,
    markersize=8,
    label="Simple LoRA (lr=1e-4)",
)
ax.plot(
    lora_1e5_x,
    lora_1e5_y,
    "s--",
    color="#7570b3",
    linewidth=2,
    markersize=7,
    label="Simple LoRA (lr=1e-5)",
)
ax.plot(
    graft_1e4_x,
    graft_1e4_y,
    "^--",
    color="#1b9e77",
    linewidth=2.5,
    markersize=8,
    label="Grafting Base->IT (lr=1e-4)",
)
ax.plot(
    graft_1e5_x,
    graft_1e5_y,
    "v:",
    color="#66a61e",
    linewidth=2,
    markersize=7,
    label="Grafting Base->IT (lr=1e-5)",
)

ax.scatter(
    [0.0909],
    [0.1782],
    color="#e7298a",
    s=130,
    marker="D",
    zorder=5,
    label="oplora-k-128",
)
ax.scatter(
    [0.0600],
    [0.1268],
    color="#e6ab02",
    s=140,
    marker="X",
    zorder=5,
    label="oplora-r90 (pre-Adam)",
)
ax.scatter(
    [0.0400],
    [0.1950],
    color="#2b83ba",
    s=150,
    marker="P",
    zorder=5,
    label="oplora-v2-r90 (post-Adam)",
)

ax.set_xlabel("New Task: termgrade-100 (Reward @ 1)", fontsize=12, fontweight="bold")
ax.set_ylabel("Old Task: gemma4_gh_pr (Reward @ 1)", fontsize=12, fontweight="bold")
ax.set_title(
    "Pareto Frontier: Old Task Retention vs New Task Acquisition",
    fontsize=14,
    fontweight="bold",
)
ax.legend(frameon=True, loc="upper right", fontsize=9.2)
ax.set_xlim(-0.005, 0.125)
ax.set_ylim(0.11, 0.345)
plt.tight_layout()
plt.savefig("paper/figures/all_methods_pareto.png", dpi=300)
plt.close()

print("Plots successfully generated in paper/figures/")
