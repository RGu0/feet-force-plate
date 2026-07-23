# DO-P4864 four-pose engineering replay fixture

This fixture holds a single de-identified, physical-device reference run for
repeatable software verification before reconnecting the device.

| Pose | Requested hold | Stored frames |
| --- | ---: | ---: |
| `open_eyes_bilateral` | 20 seconds | 414 |
| `closed_eyes_bilateral` | 20 seconds | 415 |
| `tandem_left_front` | 20 seconds | 414 |
| `tandem_right_front` | 20 seconds | 415 |

`reference-poses.npz` contains only relative `uint8` 48×64 matrix sequences.
It does not contain serial capture bytes, capture timestamps, source indexes,
absolute amplitudes, device identifiers, or operator identifiers. The fixture
is an engineering replay input only: it is not a calibrated pressure record,
a clinical dataset, or a customer-report input.

Run it through the production latest-frame-to-display projection with:

```bash
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
./scripts/local-env.sh python -m pytest \
  client/tests/test_ray_91_reference_protocol_fixture.py -q
```
