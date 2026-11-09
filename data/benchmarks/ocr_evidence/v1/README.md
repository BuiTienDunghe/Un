# OCR evidence regression fixtures v1

Ten synthetic Vietnamese images with 28 field-lookup questions. All text and
images were authored/generated locally for this experiment; no real personal
documents or third-party scan dataset is included.

`manifest.json` has paths relative to itself, expected strings and explicit
absent-field cases. `manifest.sha256` freezes this manifest before the first
rollout model run. Seven images / 18 questions are retained regression cases;
three images / 10 questions were newly generated for the rollout.

The initial new-image scores were inspected when improving layout grouping.
Later replays are diagnostic regression measurements, not an untouched held-out
estimate. Expected-string containment is a narrow lookup metric: it does not
prove semantic entailment or general OCR accuracy.
