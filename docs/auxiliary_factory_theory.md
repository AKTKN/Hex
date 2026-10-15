# Theoretical specification: logical-zero factory based on one-bit teleportation

**Purpose.** This is the scientific contract for the `AKTKN/Hex` and `AKTKN/knill_bench` implementations. It describes the intended circuit, measurable information, decoding, postselection, and validation assumptions. The initial scope is a single-logical-qubit rotated surface code, PyMatching/MWPM, and uniform Hex circuit-level noise. It is not a claim of completed implementation or numerical reproduction.

## 理論の要点（日本語）

### 1. 量子回路と状態の意味

この実験の単一 factory は **2つの logical code blocks**（A: `|0_L>`, B: `|+_L>`）を基本単位とする。両者に別々の `r_0`, `r_plus` 回の noisy SE を行い、stabilizer 符号の pure error も含む Pauli frame を古典的に確定する。続いて **B を control、A を target とする transversal CNOT** と、A の noisy destructive Z measurement を実施する。測定結果に基づいて B 上の logical X byproduct を frame に反映すると、B が新しい logical zero になる。次回は消費済み A を `|+_L>` として再準備して役割を交換する。したがって、teleportation rounds を増やしても、独立な logical zero がそれだけ生成されるわけではない。

CNOT 前の Z-stabilizer sign を `sigma_Z(A), sigma_Z(B)` とすると、測定された A の Z-check detector は概念的に `H_Z m_A XOR sigma_Z(A) XOR sigma_Z(B)` である。これは、CNOT の共役で `Z_A -> Z_A Z_B` になるためである。**Logical Z parity の raw measurement は本来ランダム**であり、detector に含めず teleportation byproduct として扱う。準備時の純誤りと logical frame の処理を省略すると detector / logical error の定義自体が変わってしまう。

### 2. Soft-information と正解ラベルの独立性

各 stage の出力は `(corrected syndrome, logical byproduct, confidence)` とし、最後に生き残る block の ideal Z destructive readout から得た `logical_error` を正解ラベルにする。この最終測定には**評価上の測定ノイズを加えない**。ただし、物理回路を流れる誤りは残す。この oracle の結果は**どの stage の復号や confidence 計算にも使用しない**。Fig. 4(d) の再現では論文と同様の **noisy final readout** を使うため、この2実験の測定条件を混同してはいけない。

Logical gap は、同じ syndrome に整合する異なる logical class の最小重み差 `Delta = |W_1-W_0|` とする。この min-sum 値は一般に posterior LLR そのものではない。Surface code では、元の parity-check matrix に logical check を安易に1行追加すると列重みが3になり、PyMatching の graphlike 条件を破る。そのため、本書の後半に記載した **2つの境界ノードを付加した graphlike lift** を使用し、`d=3` の全 `2^9` 誤りパターンの厳密列挙で、両 logical sector の最小重みを検証する。

### 3. 逆伝搬による prior 最適化の限界

`create_codecapacity_dem=False` は Hex の従来の Hamming-weight online decoding を維持する。`True` では、初期 preparation まで遡る circuit fault mechanisms を detector / logical effect に投影し、重みを導く。ただし、準備時の補正 `F_prep=D_prep(s_prep)` は通常**非線形**なので、物理 fault の線形な backpropagation だけで「準備履歴による条件付け後の厳密な online likelihood」を得られるわけではない。初版は **circuit-informed projected prior（近似）** と明記し、1-fault injection で実際の frame propagation との整合性を検証する。Hyperedge や不可視な logical mechanism は黙って削除・分解しない。

### 4. Simulation と factory cost

Postselection threshold は固定 Stim circuit の sampling 時には使わず、**保存された全 stage の gap に対して後処理で適用**する。これは、各 stage が未来の measurement を使わない限り、accepted shots の統計にバイアスを加えない。Retry の時間コストは、最初に gap が threshold を下回った stage から別計算する。回路・DEM・MWPM・補正伝搬行列は sweep point ごとに生成して cache し、shot ごとのオブジェクト構築はしない。保存するのは YAML、開始終了時刻と簡素な環境情報を持つ JSON、shot-aligned な `logical_error` / `logical_gaps` の Parquet のみを基本とする。

---

## 1. Two distinct experiments

**A. Paper reproduction.** Reproduce Fig. 4(d) of Murphy, Sahu, and Vasmer, *Simplified Circuit-Level Decoding Using Knill Error Correction* (https://arxiv.org/abs/2603.05320). The conditions are full Knill EC (not one-bit memory): eight teleportation rounds, rotated surface-code distances `d = 9, 11, 15, 21`, each Bell-resource block prepared using `d` noisy syndrome-extraction (SE) rounds, MWPM offline and online decoding, Hex's original circuit-level noise, and the paper's **noisy** final readout. Maintain the original Hamming-weight online prior as the reproduction baseline. The original figure shows `p` approximately in `[0.004, 0.010]`; document the chosen explicit grid rather than claiming access to the exact source data. Use the 95% Agresti-Coull interval when plotting. `knill_bench`'s preexisting `knill_hex_dminus2` is **not** this protocol; it uses `d-2` preparation rounds.

**B. Logical-zero factory.** This is a different physical protocol and a different readout convention: two *live* encoded blocks (`A`,`B`) rather than the `2*T+1` distinct blocks in existing full Knill circuit generation. Prepare `A` as `|0_L>` for `r_0` rounds and `B` as `|+_L>` for `r_plus` rounds; decode both preparation histories to resolve their Pauli frames including pure errors fixing stabilizer signs. Apply transversal `CNOT(B -> A)` (plus is control), destructively measure `A` in Z **with measurement noise**, decode its Z-check parity, update the surviving output `B`'s logical-X byproduct/frame, and compute the harmful-logical-X-sector confidence. For a further teleportation, reinitialize `A` as `|+_L>` for `r_plus` SE rounds and exchange roles. One stage failure rejects the whole two-block attempt. Do not confuse this with a sequence of independently created Bell-pair resources.

## 2. Stabilizer signs, measurements, and Pauli frame

Let the CSS code be `[[n,1,d]]` with binary parity checks `H_X`, `H_Z` and logical representatives `l_X`, `l_Z`. For the one-bit gadget, the consumed target block is measured in the physical Z basis, producing `m_A in GF(2)^n`. If `sigma_Z(A)` and `sigma_Z(B)` are the **correctly propagated**, preparation-history-dependent signs of the Z checks before CNOT (including the tracked corrections), then the terminal Z-check detector is schematically

\[
 s_{\rm tel}=H_Zm_A\oplus\sigma_Z(A)\oplus\sigma_Z(B).
\]

The precise implementation must derive the signs from the signed stabilizer flow and corrected measurements, not assume zero-sign checks in the raw history. Under `CNOT(B -> A)`, `Z_A -> Z_B Z_A`; the stabilizer signs therefore combine from both prepared blocks. Raw `l_Z m_A` is a legitimate random teleportation outcome, **not a detector**. Its decoded value determines the classical `X_L` byproduct/frame on `B`. A corrected sign, pure error, or byproduct must affect subsequent logical labels and detectors in the appropriate frame; no physically noiseless correction gate is to be inserted merely to simplify the simulation.

The initial known `|0_L>` is invariant under logical `Z_L`; for logical-zero quality one needs confidence in harmful logical-X flips, i.e. the logical-Z **measurement eigenvalue** after correcting the accessible syndrome. Nonlogical physical Z errors can still change stabilizer signs and must not be discarded from the frame bookkeeping.

## 3. Temporal semantics and oracle separation

The actual one-bit destructive measurement is noisy and supplies the *online* syndrome and byproduct. The **surviving final output** is measured once more in Z using a separate **noiseless terminal evaluation readout**, with an explicitly specified code-capacity terminal recovery/readout convention, to label the output `logical_error`. This terminal oracle exists only in the numerical experiment: it must never influence preparation decoding, online frame updates, logical gaps, postselection, or projected-prior construction for the candidate resource. The oracle must not be added after each intermediate teleportation in a way that collapses the continuing state.

The Fig. 4(d) experiment uses its original noisy final readout and must never inherit the factory's ideal-oracle setting. Signed Stim-flow checks (or a demonstrably equivalent frame calculation) are preferable to inferring detector signs from the simulated logical-error label.

## 4. Confidence metric and conditional errors

For one measured stage, let `s` be the corrected code-capacity-type detector vector. Let error mechanisms be indexed by `f`, with independent model probabilities `q_f`, detector matrix `H`, and logical-observable vector `L`. In a min-sum model, for logical class `b in {0,1}` define

\[
 W_b(s)=\min_{e:\,He=s,\,Le=b}\sum_f w_fe_f,\qquad
 w_f=\log\frac{1-q_f}{q_f},\qquad
 \Delta(s)=|W_1(s)-W_0(s)|.
\]

Large nonnegative `Delta` indicates stronger separation between the two candidate logical classes. It is **not generally** the exact Bayesian log-likelihood ratio, which would sum over entire error equivalence classes. With unit Hamming weights the gap has Hamming-weight units; with noise-informed `w_f` it has log-weight units, so thresholds are not interchangeable. The `decoder-confidence` repository is a reference for the *definition* and constrained-decode ideas, but its `FUTURE.md` explicitly records unresolved logical-gap correctness questions; never copy a result without tests.

At each fixed number `T_tel` of teleportations, store `gaps[shot, stage]` and the **final** output failure bit. For a threshold `theta`, postselect using the prefix condition

\[
 A_T(\theta)=\bigwedge_{j=1}^{T}\{\Delta_j\ge\theta\},\quad
 p_{\rm abort}(\theta)=1-P(A_T),\quad
 \mathrm{LER}_{\rm acc}(\theta)=P(Y_T=1\mid A_T).
\]

For an operational *early-reject* policy, the first stage with `gap < theta` determines termination and wasted work. In the simulation, it is valid to sample **all** `T` stages in advance and compute early-reject trajectories afterward, provided every stage's decoder uses only causally available measurement records and future samples do not influence earlier decisions. Accepted shot distributions are then unchanged by counterfactual simulation after an abort; resource time accounting must stop at the first failed stage. Repeatedly teleporting a single state maintains one resource; it does not generate `T` independent zero resources.

## 5. An efficient *exact* MWPM-sector-gap construction for the baseline planar graph

A naive forced-observable row appended to `H` can change graphlike matching edges (column weight at most two) into degree-three hyperedges. **Do not** assume that `Matching.from_check_matrix([H; L])` is valid.

For the initial *spatial*, independent-edge, single-logical-qubit surface-code model, use a **two-boundary-node lift** that retains graphlike columns and allows two matching decodes per batch:

1. Let `H` be the relevant detector-by-physical-error matrix (for X errors, `H_Z`), with each column of weight 1 or 2. Let `L` be the corresponding logical-Z parity of a physical-X error; `L[j]` is the logical observable flip caused by error variable `j`.
2. Solve for an internal-detector binary potential `u` such that `L[j] = u[a] XOR u[b]` on every column with two detector endpoints `(a,b)`. This can be computed by a DFS/BFS of the *internal* graph. All constraints must be checked; if inconsistent, **this construction is not applicable**.
3. On each one-detector column attached to `a`, classify its omitted endpoint as boundary `b1` if `L[j] XOR u[a] = 1`, otherwise boundary `b0`. Form `H_ext = [H; B0; B1]`; every column must now have exactly two endpoints. Reject any zero-detector columns or unresolved mapping rather than silently omit them.
4. For fixed syndrome `s` and desired logical class `b`, set `t1 = b XOR (u dot s mod 2)` and `t0 = (sum(s) mod 2) XOR t1`. Decode `s_ext = concat(s, t0, t1)` on the same **preconstructed weighted** PyMatching graph. The returned physical-error correction has weight `W_b(s)`. Compute both `W_0` and `W_1` (batch calls) and their nonnegative difference.

**Why this works.** In the extended graph, `L e = u^T H e XOR (B1 e)`, so fixing the syndrome and `B1` bit fixes the logical class. The two new boundary rows preserve graphlike degree two; matching finds each sector's minimum-weight chain. The relative logical assignment and cost must be checked against exact enumeration of **all `2^n` error patterns for `d=3`** (nine data qubits). This is an oracle for min-sum weights, not for posterior-sum log-odds. The construction assumes positive finite edge weights and a planar, graphlike, consistent binary graph. On `p=0` define an explicit deterministic handling policy instead of passing unbounded/infinite weights blindly.

For a circuit-informed DEM with hyperedges, detector-free logical events, or an inconsistent potential, this lift is **not automatically valid**. Require a proof/validated transformation or fail clearly. The first production score can use this verified baseline spatial construction; circuit-informed priors must be integrated only after their graph and logical supports pass separate checks.

## 6. Circuit-informed code-capacity-like DEM (`create_codecapacity_dem`)

The legacy Hex online Bell/teleportation decoder uses a parity-check matrix and default Hamming/unit weights. The proposed optional flag defaults to `False`, preserving those existing results. For `True`, construct fault mechanism signatures based on the **noisy Clifford circuit from the relevant preparation boundaries through the destructive teleportation measurement**. A signature consists of an online detector support, a logical-observable flip and probability `q_f` (and, when necessary, the additional preparation-detector effects). Use signed stabilizer-flow propagation and Stim DEM/fault-sensitivity tooling, not ad hoc independent data-error guesses. **A generic projection of the full DEM onto terminal detectors is not automatically the exact model of the *decoded*, frame-corrected online syndrome.**

The offline preparation frame `F_prep = D_prep(s_prep)` is usually a nonlinear function of recorded preparation syndromes. Therefore a fixed linear DEM built by physical Pauli backpropagation can, at best, be a circuit-informed **marginal or first-order approximation** to the effective online decoder problem after offline correction. If single-fault propagation through the *actual* offline decoder differs from raw projected DEM predictions, report and characterize this difference; do not claim an exact conditional posterior or reweight based on hidden truth. A future more exact conditional model may depend on each shot's observed preparation history and would be much costlier.

Combine independent mechanisms only when their **complete `(detector support, logical support)`** signatures are identical, with XOR probability `q_new = q_old + q - 2*q_old*q`, and retain detector-free logical errors for diagnostics. Do not collapse two mechanisms with equal detector support but different logical effects; never silently drop an undecomposed hyperedge. PyMatching should be instantiated only for an explicitly validated graphlike projection. If one wishes to represent the projected physical events solely as weights on `H_Z` data-error columns, label that restricted approximation separately; it is not the same as an arbitrary fault-mechanism DEM.

Cache the derived DEM / mapping / PyMatching object per **complete circuit and decoder configuration**, not per shot. Reuse Hex's correction-to-measurement map machinery and knill_bench's signed CSS sign-flow ideas. Validate fault injections (initialization, SE ancilla readout, transversal CNOT, destructive measurement), model-probability combiners, end-to-end zero-noise behaviour, and matching suitability.

## 7. Runtime and data contract

Do **not** dynamically create, mutate, or destroy Stim circuits, decoders, graphs, sparse maps, or other expensive objects per shot. Instead:

- Build and validate each `(protocol, code, d, p, r_0, r_plus, T_tel, noise, prior mode)` circuit once per sweep point; compile Stim sampler once per worker/case.
- Cache offline prep decoder instances, online matching graphs, homology-gap graph and correction-to-measurement maps. Precompute sparse conversions and batch transforms. Decode chronological stages in **batches**, updating frame-dependent derived records vectorially; never use future-stage records in an earlier score.
- Sample fixed circuits in chunks; deterministic per-point/chunk seeds, no resampling based on result quality, and no shot-level adaptive quantum branching. Compute cuts offline. Reusing a single precompiled sampler is statistically safe; reusing a *mutable* decoder with state-dependent weights across unrelated samples without reset is not.
- Store two aligned, streamed Parquet tables per point: `logical_error` (`shot_id`,`logical_error:bool`), and `logical_gaps` (`shot_id`,`gap_t001`,...,`gap_tT`: float64, nullable where necessary). The index must align exactly, with no oracle leakage into metric calculation. Store filename keys `code`, `d`, `p`, `noisemodel`, `T`, `r_0`, `r_+`. The only sweep axes are `d` and `p`.
- One run directory: `{UTC timestamp}_{experiment name}/config.yaml`, `metadata.json` (start/end UTC, run status, versions, Git SHA/dirty state, seeds, row counts and timing), and the two per-point Parquet outputs. No mandatory persisted Stim/DEM/provenance tarballs or the previous many-table schema. Use temporary/atomic files as implementation details; clean them after success. Output only samples actually performed; failure of one point must not produce apparently complete Parquet files.

For Fig. 4(d), persist `logical_error` only, preserve noisy final readout and original Hex offline/online decoding. Compare curves with the cited figure statistically; an identical RNG seed across different simulation backends does **not** imply identical shot-wise random faults.

## 8. Verification priorities and testing scope

Tests must be fast (normally `d=3`, optionally `d=5`, small shot batches and manually injected single faults). Separate heavy Monte Carlo reproduction and performance studies behind an explicit opt-in command/marker.

**Hard correctness gates:**

1. Zero-noise one-bit gadget: logical zero stays zero, syndrome zero after frame correction, byproduct is correct for both raw logical measurement outcomes.
2. Correct gate direction (`plus -> zero`), CSS stabilizer-sign propagation and inclusion of pure errors from both preparations.
3. Inject representative single faults from every circuit phase; compare expected detector and corrected-logical impact against actual decoder paths and signed Stim-flow checks.
4. Multi-teleport reused physical supports and role swaps, no intermediate oracle, correct final output oracle.
5. Same shots generate aligned logical-error and gap records; a threshold applied **only after sampling** never changes stored underlying data or amplifies failure samples through resampling.
6. Sector gap matches brute-force constrained enumeration at `d=3`, is never negative, and raises on unsupported graph topology/correlated events.
7. `create_codecapacity_dem=False` does not alter existing Hex circuits, decoding, fixed-seed results or public interfaces. `True` has audited fault-model semantics, honest approximation labels and deterministic caching.
8. Run metadata and Parquet outputs are recoverable, reproducible, and not spuriously marked complete after partial failure. Testing should avoid overly strict wall-clock assertions; inspect object creation counts and allocations instead.

## 9. Extensibility boundary

Keep distinct Python interfaces for `CodeSpec`, `PreparationPlan`, `TeleportationStage`, `MeasurementLedger/Frame`, `OnlineDecoder/ConfidenceDecoder`, `FactoryProtocol`, `SamplingCase`, and `ExperimentWriter`. Do not hardcode `d^2` or planar MWPM assumptions into generic protocol abstractions; these belong in surface-code-specific implementations/strategies. The architecture will later support color and QLDPC codes, multiple interacting factories, pool management and a complete Knill EC simulation. Preserve semantic contracts on all public results, especially the basis of logical error, stage index, Pauli-frame convention, and decoder score units.
