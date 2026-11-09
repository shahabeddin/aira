# ML problem checklist

> **Load this when the project is an ML problem.** Use it as the lens for `/grill-me` — paste this
> whole file into the grilling session so the interview covers the decisions that actually determine
> whether ML works here — and use it as the coordinator's guide when turning an ML brief into lanes
> + tickets. It pairs with [`docs/lanes-and-modules.md`](lanes-and-modules.md): an ML project
> typically carves into a **data** lane and a **modeling** lane, each owning a deep module.

## 1. Data & labeling
- **What data is available?** Sources, volume, time range, coverage. Where are the gaps and the
  biases in collection?
- **How is labeling done?** Human labels, weak supervision, proxies? Quantify label noise and
  inter-annotator agreement.
- **Taxonomy.** Define the label space precisely — classes, severities, mutually-exclusive vs.
  multi-label. A fuzzy taxonomy poisons everything downstream; settle it before any modeling.

## 2. Requirements (the "do we even need ML" guard)
- **Latency budget** — per-inference and throughput.
- **Precision / recall / FPR targets**, and the **cost asymmetry** of false positives vs. false
  negatives. Which error hurts more? This sets the operating point, not the model.
- **Will ML really add value here?** Could rules, thresholds, or heuristics match the target at a
  fraction of the cost and risk? State the non-ML baseline that ML must beat. If you can't name it,
  you're not ready to build.

## 3. Model selection
- **Start simple.** Logistic regression / single-feature thresholds as a baseline. Don't reach for
  a neural net before a linear model is tried and beaten.
- **Candidates:** traditional (logistic regression, XGBoost, random forest), small language models
  (SLMs), neural nets — and **combinations**: a **cascade** (fast cheap model → slow accurate model
  on the uncertain slice), **ensemble**, or **stacking**.
- **Which is best *for the constraints*** — latency, data size, interpretability, OOD robustness —
  not just the highest ROC on an in-distribution test set.

## 4. Features
- **Feature extraction & engineering:** what signals exist, what's leaky, and what's available at
  *inference* time (not just training). A feature you can't get in production is not a feature.
- **Representations** (NN/SLM): pretrained embeddings vs. trained-from-scratch, freezing vs.
  fine-tuning, what to tokenize / window / aggregate.

## 5. Evaluation
- **Out-of-distribution evaluation is mandatory.** Time splits, new domains, drift — report OOD
  performance separately from in-distribution. A random holdout hides the failure you'll ship.
- **Metrics tied to requirements:** ROC/PR curves at operating points, FPR at target recall,
  calibration. A single accuracy number is not evaluation.

## 6. Notebooks (reproducible artifacts)
- **Data-analysis notebooks:** comprehensive EDA for insight into the data — distributions,
  missingness, class balance, subpopulation breakdowns, label-noise inspection.
- **Modeling notebooks:** class / probability weights, ROC/PR curves, training trajectories
  (loss + metrics over epochs), confusion matrices, error analysis.

Every notebook is an **artifact**: it lands on a ticket with a path **and a checksum**, so the
verifier can reproduce it. "Done" without a checksum is an integrity flag, not a finish line (see
[`templates/README_GOVERNANCE.md`](../templates/README_GOVERNANCE.md)).
