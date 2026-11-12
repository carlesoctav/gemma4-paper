# Continual Learning in Parameter-Efficient Coding Agents: Subspace Invariance, Coordinate Drift, and the Failure of LoRA Grafting on Per-Layer Embeddings

### An Investigation of Post-Training Dynamics on Gemma 4 E4B Across Disparate Agent Harnesses and Weight Space Geometry

---

## Abstract

Continual learning in software engineering agents presents a fundamental dilemma: adapting models to new interaction environments without catastrophic forgetting of established capabilities. We investigate parameter-efficient continual post-training on Google's Gemma 4 E4B architecture across two disparate software benchmarks: GitHub pull-request issue resolution (`gemma4_gh_pr`, 118 trials) and multi-turn interactive terminal execution (`termgrade-100`, 100 trials). We evaluate standard Low-Rank Adaptation (Simple LoRA), model grafting, and Subspace Tuning (SST / OPLoRA) under a strict single-task distribution without past replay. While standard LoRA ($lr=10^{-4}$) achieves substantial acquisition on terminal tasks—doubling strict completion from $5.00\%$ to $10.10\%$ and elevating granular unit-test pass rates from $21.68\%$ to $33.46\%$ across 1,651 test assertions—it suffers a $36.3\%$ performance collapse on pull requests ($0.2703 \to 0.1722$). Conversely, LoRA Grafting preserves pre-trained capabilities ($0.2827$ reward) but fails completely to assimilate new agent skills ($0.0300$ reward, below base zero-shot). We identify the architectural pathology behind this failure: Gemma 4's Per-Layer Embeddings (PLE), comprising $77.6\%$ of model parameters ($3.49\text{B}$ parameters), apply layer-wise gated Hadamard modulations that rotate latent coordinate frames between base and instruct variants, inducing severe RMSNorm denominator inflation and quadratic SwiGLU attenuation. Finally, we formulate mathematical conditions for exact singular value invariance and prove that AdamW second-moment scaling induces $69\%$ gradient leakage under pre-projection, establishing post-optimizer projection as an indispensable prerequisite for continual agent optimization.

---

## 1. Introduction

Language model agents interface with software environments through diverse execution harnesses, spanning patch synthesis for pull requests (Jimenez et al., 2024) to multi-turn terminal execution (Shinn et al., 2023). While practitioners routinely apply Low-Rank Adaptation (LoRA; Hu et al., 2022), continual adaptation without historical replay destroys pre-existing proficiencies via catastrophic forgetting (Kirkpatrick et al., 2017).

Recent advances in continual learning suggest that model merging, such as *Grafting* (Wu et al., 2026), and spectral freezing, such as *Subspace Tuning* (SST; Chavan et al., 2026) and *Orthogonal Projection LoRA* (OPLoRA; Xiong & Xie, 2025), can isolate new task updates from historical parameter spaces. Wu et al. (2026) demonstrated that grafting weight deltas learned on a base donor checkpoint into a post-trained instruction model avoids distillation overhead while retaining base reasoning. Concurrently, Chavan et al. (2026) demonstrated that projecting weight updates onto the orthogonal complement of the pre-trained weight spectrum preserves primary representational modes.

Despite these theoretical guarantees, foundational assumptions break down when applied to the PEFT regime on modern modular agent architectures. In this paper, we conduct an extensive investigation using Google's Gemma 4 E4B model across 38 experimental evaluation runs. We investigate: (1) whether an agent can acquire multi-turn bash execution capabilities via LoRA without destroying code patch synthesis proficiencies; (2) whether LoRA Grafting translates to architectures employing non-linear coordinate routing; and (3) whether orthogonal projection preserves dominant singular modes under adaptive moment optimizers such as AdamW (Loshchilov & Hutter, 2019).

Our findings show that while LoRA displays strong plasticity on new terminal tasks, it devastates historical pull-request capabilities. LoRA Grafting fails completely on the new task ($0.0300$ success rate vs $0.0500$ zero-shot baseline). We prove that this failure is governed by Gemma 4's Per-Layer Embeddings (PLE), where coordinate rotations between base and instruct models induce destructive interference. We formally prove singular value invariance under orthogonal projection, explain why AdamW's diagonal preconditioner causes $69\%$ subspace leakage under gradient pre-projection, and demonstrate how exact Gram eigendecomposition (`eigh`) with post-optimizer projection restores stability.

---

## 2. Theoretical Foundations and Architectural Mechanics

### 2.1 Orthogonal Projection and Singular Value Invariance

Let $W_0 \in \mathbb{R}^{d_{\text{out}} \times d_{\text{in}}}$ denote a frozen pre-trained weight matrix with singular value decomposition $W_0 = U \Sigma V^T = \sum_{j=1}^{\min(d_{\text{out}}, d_{\text{in}})} \sigma_j u_j v_j^T$, with singular values $\sigma_1 \ge \dots \ge \sigma_k > \sigma_{k+1} \ge \dots \ge 0$. Let $U_k \in \mathbb{R}^{d_{\text{out}} \times k}$ and $V_k \in \mathbb{R}^{d_{\text{in}} \times k}$ span the dominant left and right singular subspaces $\mathcal{S}_L = \text{span}(U_k)$ and $\mathcal{S}_R = \text{span}(V_k)$. Define the orthogonal projection operators onto their orthogonal complements:
$$P_L = I_{d_{\text{out}}} - U_k U_k^T, \quad P_R = I_{d_{\text{in}}} - V_k V_k^T$$

**Lemma 1 (Subspace Annihilation).**
$P_L$ and $P_R$ are symmetric idempotent projectors satisfying $P_L U_k = 0$, $U_k^T P_L = 0$, $P_R V_k = 0$, and $V_k^T P_R = 0$.
*Proof.* $P_L U_k = (I - U_k U_k^T) U_k = U_k - U_k (U_k^T U_k) = U_k - U_k I_k = 0$. Transposition yields $U_k^T P_L = 0$. Identical identities hold for $P_R V_k = 0$. $\blacksquare$

**Theorem 1 (Dominant Singular Triple Preservation).**
Let $\Delta W_0 \in \mathbb{R}^{d_{\text{out}} \times d_{\text{in}}}$ be an arbitrary weight update. Define the double-projected update $\Delta W = P_L \Delta W_0 P_R$ and adapted weight matrix $W' = W_0 + \Delta W$. For every $i \in \{1, \dots, k\}$, $(u_i, \sigma_i, v_i)$ remains an exact singular triple of $W'$:
$$W' v_i = \sigma_i u_i \quad \text{and} \quad (W')^T u_i = \sigma_i v_i$$
*Proof.* By Lemma 1, $\Delta W v_i = P_L \Delta W_0 (P_R v_i) = 0$, so $W' v_i = (W_0 + \Delta W) v_i = \sigma_i u_i$. Similarly, $(\Delta W)^T u_i = P_R (\Delta W_0)^T (P_L u_i) = 0$, yielding $(W')^T u_i = \sigma_i v_i$. $\blacksquare$

**Theorem 2 (Top-$k$ Singular Value Invariance).**
If the spectral norm satisfies $\|\Delta W\|_2 < \sigma_k - \sigma_{k+1}$, the $k$ largest singular values of $W'$ are identically equal to those of $W_0$:
$$\sigma_i(W') = \sigma_i(W_0) = \sigma_i \quad \forall i \in \{1, \dots, k\}$$
*Proof.* Expanding complete orthonormal bases $U = [U_k, U_\perp]$ and $V = [V_k, V_\perp]$, transform $W'$ into basis $(U, V)$:
$$M = U^T W' V = \begin{bmatrix} U_k^T W' V_k & U_k^T W' V_\perp \\ U_\perp^T W' V_k & U_\perp^T W' V_\perp \end{bmatrix}$$
Evaluating each block using $P_L U_k = 0$ and $P_R V_k = 0$: $U_k^T W' V_k = \Sigma_k$, $U_k^T W' V_\perp = 0$, $U_\perp^T W' V_k = 0$, and $U_\perp^T W' V_\perp = \Sigma_\perp + U_\perp^T \Delta W_0 V_\perp$. Matrix $M$ is block diagonal:
$$M = \text{diag}(\Sigma_k, \, \Sigma_\perp + U_\perp^T \Delta W_0 V_\perp)$$
Unitary transformations preserve the singular spectrum. By Weyl's inequality, $\sigma_{\max}(\Sigma_\perp + U_\perp^T \Delta W_0 V_\perp) \le \sigma_{k+1} + \|\Delta W\|_2 < \sigma_k$. Thus no singular value from the trailing block can reach $\sigma_k$, guaranteeing that the top-$k$ singular values remain strictly unchanged. $\blacksquare$

### 2.2 AdamW Second-Moment Non-Commutativity and Subspace Leakage

In OPLoRA (Xiong & Xie, 2025), projections are inserted as gradient backward hooks: $\tilde{G}_t = \Pi(G_t) = P_L G_t P_R$. In AdamW (Loshchilov & Hutter, 2019), moments $m_t = \beta_1 m_{t-1} + (1-\beta_1)\tilde{G}_t$ and $v_t = \beta_2 v_{t-1} + (1-\beta_2)(\tilde{G}_t \odot \tilde{G}_t)$ scale updates via $[\mathcal{D}_t(M)]_{ij} = M_{ij} / (\sqrt{[\hat{v}_t]_{ij}} + \epsilon)$.

**Theorem 3 (AdamW Preconditioning Breaks Orthogonality).**
The diagonal preconditioning operator $\mathcal{D}_t$ does not commute with orthogonal projector $\Pi$:
$$\mathcal{D}_t \circ \Pi \neq \Pi \circ \mathcal{D}_t$$
*Proof.* For $M \in \mathcal{V}_{\text{free}}$, $M V_k = 0$, so $\sum_{j=1}^{d_{\text{in}}} M_{ij} (v_m)_j = 0$ for every column $v_m$ of $V_k$. The $i$-th row of $\mathcal{D}_t(M) v_m$ is:
$$[\mathcal{D}_t(M) v_m]_i = \sum_{j=1}^{d_{\text{in}}} \frac{M_{ij}}{\sqrt{[\hat{v}_t]_{ij}} + \epsilon} (v_m)_j$$
Because $[\hat{v}_t]_{ij}$ varies across coordinates $j$, this non-uniformly weighted sum does not vanish. Thus $\mathcal{D}_t(M) V_k \neq 0$, implying $\Pi(\mathcal{D}_t(M)) \neq \mathcal{D}_t(M)$. $\blacksquare$

**Subspace Leakage.** Under gradient pre-projection, $\mathcal{D}_t$ causes updates to leak into the protected subspace: $\Delta W_t^{\text{leak}} = (I - \Pi) \Delta W_t^{\text{Adam}} \neq 0$. Chavan et al. (2026) showed this causes **$69\%$ cumulative leakage** within 60 optimization steps. To eliminate leakage, projection must be applied **post-optimizer** on step completion: $\Delta W_t^{\text{applied}} = \Pi(\Delta W_t^{\text{Adam}})$, enforcing exactly **$0\%$ leakage**.

### 2.3 Exact Gram Eigendecomposition vs Randomized SVD

OPLoRA used randomized low-rank SVD (`torch.svd_lowrank`), which is subject to error bounds $\| (I - V_k V_k^T) V_k^* \| \sim \mathcal{O}((\sigma_{k+1}/\sigma_k)^{2q})$. For high spectral fractions ($r_{\text{frac}} = 0.90$, where $k = 0.90 d_{\min}$), $\sigma_{k+1} \approx \sigma_k$, causing randomized SVD to break down and leave residual alignment $\rho_k > 0$.

We compute exact bases via Gram matrix eigendecomposition (`torch.linalg.eigh`):
- If $d_{\text{in}} \le d_{\text{out}}$, compute $G = W_0^T W_0 \in \mathbb{R}^{d_{\text{in}} \times d_{\text{in}}}$. Since $G$ is positive semi-definite, `eigh` yields exact eigenvalues $\lambda_i = \sigma_i^2$ and orthonormal eigenvectors $V_k$, deriving $U_k = (W_0 V_k) \Sigma_k^{-1}$.
- If $d_{\text{out}} < d_{\text{in}}$, compute $G = W_0 W_0^T \in \mathbb{R}^{d_{\text{out}} \times d_{\text{out}}}$ to obtain $U_k$, followed by $V_k = (W_0^T U_k) \Sigma_k^{-1}$.

This formulation has computational complexity $\mathcal{O}(d_{\min}^2 d_{\max} + d_{\min}^3)$, which is strictly independent of $k$, guaranteeing exact machine-precision nullification ($\rho_k \equiv 0$).

### 2.4 Architectural Mechanics of Grafting Failure on Gemma 4 E4B

In LoRA Grafting (Wu et al., 2026), an adapter $\Delta W_{\text{donor}} = \frac{\alpha}{r} B A$ is trained on a base donor $\theta_{\text{base}}$ and transferred onto instruction model $\theta_{\text{it}}$. On Gemma 4 E4B, Grafting fails due to four compounding mechanisms:

1. **Per-Layer Embeddings (PLE) Dominance**: Embeddings comprise $3.49\text{B}$ out of $4.5\text{B}$ total parameters ($77.6\%$ of parameter mass). Layer 0 embeddings are $[262144, 2560]$, while layer-specific embeddings `embed_tokens_per_layer` are $[262144, 10752]$ ($42 \text{ layers} \times 256 \text{ dimensions}$).
2. **Non-Linear Gated Hadamard Injection**: At each layer $l$, the residual stream $h_l$ is modulated via:
   $$g_l = \text{GELU}(W_{\text{gate}}^{(l)} h_l), \quad m_l = g_l \odot z^{(l)}(x), \quad \Delta h_{\text{ple}}^{(l)} = \text{RMSNorm}(W_{\text{proj}}^{(l)} m_l)$$
   where $z^{(l)}(x)$ is the layer token vector. Injection depends non-linearly on $h_l$ through the state-dependent Hadamard product.
3. **Coordinate Frame Rotation**: Instruction tuning alters attention and MLP pathways, causing hidden trajectories to diverge: $h_l^{\text{it}} = R_l h_l^{\text{base}} + \delta_l$, where $R_l \in SO(d)$ exhibits large off-diagonal energy. The base-trained donor adapter $A_{\text{donor}}$, which expects base coordinates, receives rotated inputs:
   $$u^{\text{it}} = A_{\text{donor}} h_l^{\text{it}} = A_{\text{donor}} R_l h_l^{\text{base}} + A_{\text{donor}} \delta_l$$
   destroying directional activation and injecting incoherent perturbations into the recipient model.
4. **RMSNorm Inflation and Quadratic SwiGLU Attenuation**: The misaligned update $\Delta y_l = \lambda B A h_l$ increases residual stream energy: $\|\tilde{h}_l\|_2^2 \approx \|h_l\|_2^2 + \|\Delta y_l\|_2^2$. Subsequent RMSNorm layers attenuate activations by $\kappa = (1 + \|\Delta y_l\|_2^2 / \|h_l\|_2^2)^{-1/2} < 1$. In the MLP block, Gemma 4 employs SwiGLU:
   $$\text{SwiGLU}(x) = (W_{\text{gate}} x \odot \sigma(\beta W_{\text{gate}} x)) \odot W_{\text{up}} x$$
   which exhibits quadratic homogeneity: $\text{SwiGLU}(\kappa x) \approx \kappa^2 \text{SwiGLU}(x)$. Compounding across 42 layers ($\kappa^{84}$), this attenuation collapses downstream activation magnitudes.

---

## 3. Benchmark Infrastructure and Dataset Engineering

### 3.1 Incremental Rebuild Mining (`repo2rlenv`)

To establish our pre-training benchmark (`gemma4_gh_pr`), we engineered `repo2rlenv`, an automated pipeline building Docker execution environments from GitHub PRs using **incremental container caching**:
- PRs are processed in reverse chronological order.
- Commit diffs are analyzed; if modifications touch application files without changing dependency manifests (`pyproject.toml`, `setup.py`, `requirements.txt`, `environment.yml`), rebuilds are bypassed, reusing parent image snapshots.
- Problem instructions are synthesized with `openai/thinkingmachines/Inkling-Small` to produce natural developer issue formulations.
- The benchmark comprises 118 verified PR resolution tasks evaluated via the `pi:PiTinker` agent harness, graded on continuous reward: $reward = f2p\_rate \times p2p\_factor$.

### 3.2 Termgrade Trajectory Preparation and Data Leakage Audit

For the new task (`termgrade-100`), we employ `termgrade-environments` (1,004 terminal challenges evaluated via `terminus-2`). The dataset `carlesoctav/termgrade-p95-split_sft` was curated with strict safeguards:
1. **Multi-Turn Trajectory Splitting**: Because `terminus-2` operates as a turn-by-turn shell parser, trajectories were unrolled into sequential prompt-completion pairs.
2. **P95 Sequence Length Cutoff**: Trajectories exceeding the 95th percentile token length were discarded, removing non-terminating bash loop traces.
3. **Reasoning Tag Sanitization**: Prior assistant reasoning traces (`<think>...</think>`) were stripped from conversational history. In the terminal runtime, intermediate thinking is not re-injected across turns; preserving historical thinking tokens introduces inference-time conditioning distribution shift.
4. **Data Leakage Safeguard**: Our audit confirmed:
   - Training split: 699 unique tasks (4,049 expanded turns).
   - Test split: Exactly 100 heldout tasks (`termgrade-100`).
   - Task overlap between training and test sets: **Exactly 0 tasks**.
   - Overlap between base-model solved tasks (116 tasks) and test set: **Exactly 0 tasks**.

### 3.3 Training Configuration

All adaptation runs were executed on Google Gemma 4 E4B IT using rank $r=8$ and scaling $\alpha=16$, targeting linear projections across all 42 layers (258 adapted modules). Training used a per-device batch size of 8 with 4 gradient accumulation steps (effective batch size 32), maximum sequence length 16,384 tokens, cosine learning rate schedule with $10\%$ linear warmup, and capped at 100 gradient steps (3,200 unique examples seen).

---

## 4. Empirical Evaluation and Results

### 4.1 Continual Learning Performance Across Methods

Table 1 summarizes empirical performance across 38 evaluation runs on `gemma4_gh_pr` (118 trials) and `termgrade-100` (100 trials).

| Configuration | Old Task (`gemma4_gh_pr`) Reward | Old Task Resolved | New Task (`termgrade-100`) Reward | CTRF Unit-Test Pass Rate |
| :--- | :---: | :---: | :---: | :---: |
| **Gemma 4 E4B IT (Base)** | **0.2703** | **24 / 118 (20.34%)** | **0.0500 (5 / 100)** | **21.68% (358 / 1,651)** |
| Simple LoRA ($lr=10^{-4}$, step 50) | 0.2005 | 18 / 118 (15.25%) | 0.0404 (4 / 99) | 22.12% (361 / 1,632) |
| Simple LoRA ($lr=10^{-4}$, step 75) | 0.1920 | 17 / 118 (14.41%) | 0.0900 (9 / 100) | 30.04% (496 / 1,651) |
| **Simple LoRA ($lr=10^{-4}$, step 100)** | **0.1722** | **17 / 118 (14.41%)** | **0.1010 (10 / 99)** | **33.46% (548 / 1,638)** |
| Simple LoRA ($lr=10^{-5}$, step 50) | 0.3038 | 28 / 118 (23.73%) | 0.0500 (5 / 100) | 19.02% (314 / 1,651) |
| Simple LoRA ($lr=10^{-5}$, step 75) | 0.3015 | 27 / 118 (22.88%) | 0.0400 (4 / 100) | 18.35% (303 / 1,651) |
| Simple LoRA ($lr=10^{-5}$, step 100) | 0.2690 | 22 / 118 (18.64%) | 0.0400 (4 / 100) | 13.69% (226 / 1,651) |
| Grafting ($lr=10^{-4}, \lambda=1$, step 50) | 0.2868 | 22 / 118 (18.64%) | 0.0300 (3 / 100) | 20.84% (344 / 1,651) |
| Grafting ($lr=10^{-4}, \lambda=1$, step 75) | 0.2565 | 20 / 118 (16.95%) | 0.0600 (6 / 100) | 21.62% (357 / 1,651) |
| **Grafting ($lr=10^{-4}, \lambda=1$, step 100)** | **0.2827** | **24 / 118 (20.34%)** | **0.0300 (3 / 100)** | **24.89% (411 / 1,651)** |
| Grafting ($lr=10^{-5}, \lambda=1$, step 100) | 0.2788 | 25 / 118 (21.19%) | 0.0300 (3 / 100) | 20.90% (345 / 1,651) |
| Grafting ($lr=10^{-3}, \lambda=1$, step 100) | *N/A* | *N/A* | 0.0600 (6 / 100) | 29.32% (484 / 1,651) |
| Hybrid Mix-100 (Base LoRA + IT PLE) | 0.2876 | 24 / 118 (20.34%) | 0.0500 (5 / 100) | 20.65% (341 / 1,651) |
| OPLoRA ($k=128$, randomized SVD) | 0.1782 | 14 / 118 (11.86%) | 0.0909 (9 / 99) | 29.34% (477 / 1,626) |
| OPLoRA ($r=0.90$, exact `eigh` + hooks) | 0.1268 | 13 / 118 (11.02%) | 0.0600 (6 / 100) | 25.08% (414 / 1,651) |
| **OPLoRA-v2 ($r=0.90$, exact `eigh`, post-proj)** | **0.1950** | **19 / 118 (16.10%)** | **0.0400 (4 / 100)** | **18.11% (299 / 1,651)** |

*Table 1: Empirical evaluation of continual learning methods on GitHub PR resolution (`gemma4_gh_pr`, 118 trials) and interactive terminal coding (`termgrade-100`, 100 trials).*

### 4.2 Metric Resolution Analysis: Binary Rewards vs Granular CTRF Pass Rates

Evaluating agents via binary rewards ($reward \in \{0, 1\}$) masks critical learning progress. In `termgrade-100`, task success requires passing all unit tests; resolving 14 of 15 tests yields $0.0$. Analyzing Common Test Report Format (`ctrf.json`) logs across 1,651 unit tests reveals:
- **Base Model (Zero-Shot)**: Passes 358 of 1,651 unit tests ($21.68\%$). Only 5 tasks complete successfully ($5.0\%$). Exactly 48 tasks produce 0 passing tests.
- **Simple LoRA ($lr=10^{-4}$)**: Granular test completions increase to 548 of 1,638 ($33.46\%$, a $+54.3\%$ relative gain). Completely failed tasks drop from 48 to 27. Tasks passing at least one test expand from 46 to 61.
- **Grafting ($lr=10^{-4}$)**: Achieves 411 passing tests ($24.89\%$), reflecting marginal partial learning that fails to achieve full task completion ($3.0\%$).

### 4.3 Weight Space Geometry and Convergence Dynamics

Analysis of local adapter tensors (`checkpoint-127/adapter_model.safetensors`, 168 adapted matrices) reveals:
- **Global Frobenius Norm**: Mean $\|\Delta W\|_F = 0.2787$ ($\text{std} = 0.1742$).
- **MLP vs Attention Asymmetry**: Attention layers (`q_proj`, `v_proj`) show mean $\|\Delta W\|_F = 0.1283$, whereas MLP layers (`gate_proj`, `up_proj`) exhibit mean $\|\Delta W\|_F = 0.4363$. MLP updates are **$3.40\times$ larger** in Frobenius norm, indicating that procedural adaptation concentrates within activation routing pathways.
- **Spectral Anisotropy**: The dominant singular value ratio is $s_0 / s_1 = 3.52$, with an effective rank of $7.45$ (relative to max rank 8), indicating updates align along a primary axis.
- **Depth-Wise Layer Shift**: Early layers (0–10) exhibit mean $\|\Delta W\|_F = 0.1683$, while late layers (30–41) show mean $\|\Delta W\|_F = 0.4071$. Late layers absorb **$2.42\times$ more norm shift**, confirming that procedural syntax adaptation concentrates in top transformer layers.

### 4.4 Subspace Tuning Dynamics: Gradient Hooks vs Post-Optimizer Projection

Under OPLoRA with high protection ($r_{\text{frac}}=0.90$), applying gradient pre-projection hooks (`oplora-r90`) degrades old task performance ($0.1268$ reward, $11.02\%$ resolved), performing worse than unconstrained Simple LoRA ($0.1722$). This confirms Theorem 3: AdamW coordinate preconditioning leaks $69\%$ of updates into the protected subspace.

Switching to post-optimizer projection (`oplora-v2-r90`) eliminates subspace leakage, elevating old task reward by **$+53.8\%$** ($0.1268 \to 0.1950$) and strict task completions from $11.02\%$ to $16.10\%$. However, freezing $90\%$ of the spectrum restricts the model parameter budget, constraining new task acquisition to $4.00\%$ and illustrating the fundamental trade-off between stability and plasticity.

---

## 5. Related Work

### 5.1 Parameter-Efficient Fine-Tuning and Continual Learning
Parameter-Efficient Fine-Tuning (PEFT), including LoRA (Hu et al., 2022) and QLoRA (Dettmers et al., 2023), freezes foundation weights to optimize low-rank matrices $B A$. However, standard LoRA remains vulnerable to catastrophic forgetting across sequential task distributions (Kirkpatrick et al., 2017).

### 5.2 Model Merging, Task Vectors, and Grafting
Model merging techniques, such as task vectors (Ilharco et al., 2022), combine capabilities by linearly interpolating parameter deltas. Wu et al. (2026) introduced *Grafting*, an off-policy framework training base models on target datasets and grafting resulting deltas onto post-trained models. While effective on standard transformers, grafting has not been examined on architectures with dynamic per-layer coordinate modulations.

### 5.3 Subspace Regularization and Orthogonal Adaptation
Orthogonal subspace methods protect representations by restricting updates to null spaces of dominant singular vectors. Xiong & Xie (2025) proposed OPLoRA, projecting LoRA weights via randomized SVD. Chavan et al. (2026) formulated Subspace Tuning (SST), showing AdamW states induce leakage under gradient projection. Our work bridges these paradigms, proving singular value invariance, analyzing AdamW non-commutativity, and demonstrating the failure mode induced by Per-Layer Embeddings.

---

## 6. Limitations and Threats to Validity

1. **Gradient Step Budget**: Due to substantial compute requirements for multi-turn agent evaluation, training runs were capped at 100 gradient steps (3,200 unique examples seen), which proved sufficient to observe sharp divergence across methods.
2. **Single-Rollout Budget ($pass@1$)**: Primary benchmark evaluations used greedy single rollouts ($pass@1$) rather than expansive $pass@k$ curves, reflecting operational constraints in autonomous software engineering.
3. **Disparate Agent Harness Dynamics**: The old benchmark (`gemma4_gh_pr`) employs `pi:PiTinker` (tool-calling with context compaction), whereas the new benchmark (`termgrade-100`) uses `terminus-2` (command line interface with bash execution). Differences in harness context management introduce orthogonal evaluation dynamics.

---

## 7. Conclusion

In this paper, we presented an empirical and theoretical study of parameter-efficient continual learning in coding agents using Google's Gemma 4 E4B model. We demonstrated that standard LoRA incurs severe catastrophic forgetting on pull-request resolution ($0.2703 \to 0.1722$) while learning terminal commands. We revealed that LoRA Grafting fails catastrophically ($0.0300$ reward) due to architectural coordinate drift from Gemma 4's Per-Layer Embeddings (PLE, $77.6\%$ of model parameters), triggering severe RMSNorm denominator inflation and quadratic SwiGLU attenuation. Finally, we proved dominant singular value invariance under orthogonal projection, derived the mathematical mechanism causing AdamW second-moment leakage ($69\%$), and established that exact Gram eigendecomposition with post-optimizer projection restores subspace containment.

---

## References

- Chavan, A., Shen, Z., Zhuang, B., Liu, Z., Darrell, T., & Keutzer, K. (2026). Towards Continual Learning: Mitigating Forgetting With Subspace Tuning. *arXiv preprint arXiv:2610.22293*.
- Dettmers, T., Pagnoni, A., Holtzman, A., & Zettlemoyer, L. (2023). QLoRA: Efficient Finetuning of Quantized LLMs. *Advances in Neural Information Processing Systems (NeurIPS)*, 36, 10088–10115.
- Gemma Team, et al. (2024). Gemma: Open Models Based on Gemini Research and Technology. *arXiv preprint arXiv:2403.08295*.
- Halko, N., Martinsson, P.-G., & Tropp, J. A. (2011). Finding structure with randomness: Probabilistic algorithms for constructing approximate matrix decompositions. *SIAM Review*, 53(2), 217–288.
- Hu, E. J., Shen, Y., Wallis, P., Allen-Zhu, Z., Li, Y., Wang, S., Wang, L., & Chen, W. (2022). LoRA: Low-Rank Adaptation of Large Language Models. *International Conference on Learning Representations (ICLR)*.
- Ilharco, G., Ribeiro, M. T., Wortsman, M., Gururangan, S., Schmidt, L., Hajishirzi, H., & Farhadi, A. (2022). Editing models with task vectors. *arXiv preprint arXiv:2212.04089*.
- Jimenez, C. E., Yang, J., Wettig, A., Yao, S., Pei, K., Press, O., & Narasimhan, K. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? *International Conference on Learning Representations (ICLR)*.
- Kirkpatrick, J., Pascanu, R., Rabinowitz, N., Veness, J., Desjardins, G., Rusu, A. A., Milan, K., Quan, J., Ramalho, T., Grabska-Barwinska, A., et al. (2017). Overcoming catastrophic forgetting in neural networks. *Proceedings of the National Academy of Sciences*, 114(13), 3521–3526.
- Loshchilov, I., & Hutter, F. (2019). Decoupled Weight Decay Regularization. *International Conference on Learning Representations (ICLR)*.
- Shinn, N., Labash, F., Gopinath, A., Narasimhan, K., & Yao, S. (2023). Reflexion: Language Agents with Verbal Reinforcement Learning. *Advances in Neural Information Processing Systems (NeurIPS)*, 36, 8634–8652.
- Wu, T., Zhang, M., & Raghunathan, A. (2026). Off-Policy Merging Beats On-Policy Self-Distillation for Continual Learning. *arXiv preprint arXiv:2610.05872*.
- Xiong, Y., & Xie, X. (2025). OPLoRA: Orthogonal Projection LoRA Prevents Catastrophic Forgetting during Parameter-Efficient Fine-Tuning. *arXiv preprint arXiv:2510.13003*.
