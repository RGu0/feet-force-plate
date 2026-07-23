# Display-Only Heatmap Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the P-07 48×64 pressure heatmap visually continuous and robust to isolated sensor artefacts without changing any source frame, physical interpretation, local analysis, COP, load metrics, reliable storage, or report data.

**Architecture:** Add a stateful, UI-only `HeatmapDisplayRefiner` that copies the immutable `DisplayFrame.relative_heatmap`, owns a three-frame temporal cache, and returns a new 48×64 render matrix. `HeatmapWidget` alone invokes it; `DisplayFrame` and all workflow/local-analysis objects remain untouched. The output is masked back to measured contact after conditional cleanup so smoothing cannot expand the contact outline.

**Tech Stack:** Python 3.11+, NumPy, SciPy `ndimage.gaussian_filter`, PySide6, pytest-qt.

## Global Constraints

- Work only on the display copy; never mutate `DisplayFrame`, raw frames, spool data, `LocalAnalysisResult`, COP, load metrics, or reports.
- Keep the RAY-84 latest-only boundary: old display frames may be overwritten without affecting reliable capture/upload.
- Do not use a fixed foot template, 5×5/box blur artefact removal, or any operation that spreads isolated values beyond measured contact.
- Empty current frames must be rendered empty, even if recent display history contained contact.
- All Python execution uses `./scripts/local-env.sh`; no repository-local `.venv`.
- RAY-110 remains untouched because it is Backlog and blocked by RAY-105.

---

### Task 1: Define and prove the pure display refiner

**Files:**
- Create: `client/app/heatmap_display.py`
- Create: `client/tests/test_heatmap_display_refiner.py`

**Interfaces:**
- Produces: `HeatmapDisplayConfig` and `HeatmapDisplayRefiner.refine(values: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]`.
- Consumes: only a 48×64 numeric display matrix; it has no import from device, workflow, reporting, storage, or local analysis modules.

- [ ] **Step 1: Write failing fixture tests**

```python
def test_refiner_removes_a_single_high_outlier_without_spreading_it():
    source = _matrix_with_cluster_and_one_bright_pixel()
    refined = HeatmapDisplayRefiner().refine(_as_tuple(source))
    assert refined[5][5] == 0.0
    assert max(refined[row][column] for row in range(4, 7) for column in range(4, 7)) == 0.0

def test_refiner_fills_a_single_hole_but_preserves_a_two_by_two_cluster():
    refined_hole = HeatmapDisplayRefiner().refine(_as_tuple(_cluster_with_hole()))
    refined_cluster = HeatmapDisplayRefiner().refine(_as_tuple(_two_by_two_cluster()))
    assert refined_hole[22][22] > 0.0
    assert sum(value > 0.0 for row in refined_cluster for value in row) >= 4

def test_refiner_keeps_empty_current_frame_empty_and_does_not_mutate_source():
    refiner = HeatmapDisplayRefiner()
    source = _cluster_with_hole()
    before = source.copy()
    refiner.refine(_as_tuple(source))
    assert np.array_equal(source, before)
    assert not np.any(np.asarray(refiner.refine(_as_tuple(np.zeros((48, 64))))))
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
./scripts/local-env.sh python -m pytest client/tests/test_heatmap_display_refiner.py -q
```

Expected: collection fails because `client.app.heatmap_display` does not exist.

- [ ] **Step 3: Implement the minimum display-only pipeline**

```python
@dataclass(frozen=True, slots=True)
class HeatmapDisplayConfig:
    temporal_window: int = 3
    hampel_scale: float = 3.5
    mad_scale: float = 1.4826
    p99_relative_threshold: float = 0.08
    island_max_pixels: int = 2
    gamma: float = 0.75
    gaussian_sigma: float = 0.9

class HeatmapDisplayRefiner:
    def refine(self, values):
        current = _copied_48x64(values)
        if not np.any(current > 0):
            self._history.clear()
            return _as_tuple(np.zeros_like(current))
        temporal = _temporal_median_with_last_three_copies(current, self._history)
        cleaned = _conditional_hampel(temporal, self.config)
        contact = _clean_contact_mask(cleaned, self.config)
        robust = _p99_normalize(cleaned, contact)
        smoothed = gaussian_filter(np.power(robust, self.config.gamma), self.config.gaussian_sigma)
        return _as_tuple(np.where(contact, smoothed, 0.0))
```

`_conditional_hampel` replaces a high candidate only when it has no adjacent similarly high contact, preserving 2×2-or-larger clusters. Low candidates are replaced only when enclosed by valid neighbouring contact. `_clean_contact_mask` removes 4-connected 1–2-pixel islands and fills only one-pixel holes whose four cardinal neighbours are already contact.

- [ ] **Step 4: Run the fixture tests and verify GREEN**

Run the Step 2 command. Expected: all refiner tests pass.

### Task 2: Connect the refiner only to Qt rendering

**Files:**
- Modify: `client/app/heatmap.py`
- Modify: `client/tests/test_ray_84_qt.py`

**Interfaces:**
- Consumes: immutable `DisplayFrame.relative_heatmap`.
- Produces: `HeatmapWidget.rendered_heatmap` for visual-regression tests; `HeatmapWidget.display_frame` continues to be the original object for COP/text metrics.

- [ ] **Step 1: Write failing widget assertions**

```python
def test_widget_refinement_does_not_change_display_frame_or_its_metrics(qtbot):
    frame = build_display_frame(_counts_with_outlier(), sequence=7, ...)
    before = (frame.cop_x, frame.cop_y, frame.left_load_percent, frame.right_load_percent, frame.total_relative_load)
    widget = HeatmapWidget()
    widget.set_display_frame(frame)
    assert widget.display_frame is frame
    assert (frame.cop_x, frame.cop_y, frame.left_load_percent, frame.right_load_percent, frame.total_relative_load) == before
    assert widget.rendered_heatmap[5][5] == 0.0
```

- [ ] **Step 2: Run it and verify RED**

Run:

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_ray_84_qt.py -q
```

Expected: failure because `rendered_heatmap` is not exposed and the current box blur spreads the outlier.

- [ ] **Step 3: Implement the narrow widget integration**

```python
def set_display_frame(self, frame: DisplayFrame) -> None:
    self._display_frame = frame
    self._rendered_heatmap = self._refiner.refine(frame.relative_heatmap)
    self.update()
```

Render only `_rendered_heatmap`; leave the existing `frame` object as the source for COP trail, current COP point, and all textual information.

- [ ] **Step 4: Verify widget and RAY-84 regression tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  client/tests/test_heatmap_display_refiner.py \
  client/tests/test_ray_84_display_model.py \
  client/tests/test_ray_84_qt.py \
  client/tests/test_ray_84_controller.py -q
```

Expected: all pass; no test changes source/display frame metrics.

### Task 3: Produce repeatable visual evidence and close the implementation slice

**Files:**
- Create: `scripts/capture_heatmap_refinement.py`
- Create: `docs/evidence/linear/RAY-84/heatmap-refinement-before.png`
- Create: `docs/evidence/linear/RAY-84/heatmap-refinement-after.png`
- Modify: `docs/evidence/linear/RAY-84/README.md`

- [ ] **Step 1: Add a deterministic fixture capture command**

The script uses a synthetic 48×64 fixture with a compact contact region, one bright isolated point, and one internal hole. It renders source and refined matrices with the same colour map, writes two named PNGs, and never reads a serial device or changes a report object.

- [ ] **Step 2: Execute offscreen capture and tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python scripts/capture_heatmap_refinement.py \
  --output docs/evidence/linear/RAY-84
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest client/tests/test_heatmap_display_refiner.py client/tests/test_ray_84_*.py -q \
  --junitxml=docs/evidence/linear/RAY-84/pytest-heatmap-refinement.xml
```

Expected: two deterministic contrast images and a passing JUnit result.

- [ ] **Step 3: Record evidence boundaries**

Document the configuration values, changed files, exact test results, before/after image paths, and the explicit limitation that this is fixture/offscreen evidence only—not real DO-P4864, target-display, or clinical/physical-validation evidence.

- [ ] **Step 4: Commit only the RAY-84 files and update Linear**

Stage only the refiner, widget integration, tests, capture script, and RAY-84 evidence. Return RAY-84 to `In Review` rather than `Done` unless real-device and manual acceptance evidence exists. Do not update RAY-110.
