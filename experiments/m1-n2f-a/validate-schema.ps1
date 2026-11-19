# Validate the frozen deck encodings and the N2E reference examples with PowerShell 7.
$ErrorActionPreference = 'Stop'
$schema = Join-Path $PSScriptRoot '../m1-n2e/schema.json'
$script = @"
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1])))
from study_design import HERE, read, load_catalog, deck_from_root

catalog = load_catalog()
seen = set()
for item in read(HERE / "manifest.json"):
    case = item["case"]
    if case["deck_sha256"] in seen:
        continue
    seen.add(case["deck_sha256"])
    spec = case["spec"]
    deck = deck_from_root(spec["character"], spec["deck"])
    for mode in ("identity", "mechanics"):
        payload = catalog.encode_deck(deck, mode)
        assert payload["content_sha256"] == case["deck_sha256"]
        print(json.dumps(payload))
example = read(HERE.parent / "m1-n2e/example.json")
for name in ("card_spec", "identity_deck", "mechanics_deck", "context"):
    print(json.dumps(example[name]))
for binding in example["bindings"]:
    print(json.dumps(binding))
for card in read(HERE.parent / "m1-n2e/cards.json")["cards"]:
    print(json.dumps(catalog.encode_card_spec(card["id"])))
"@
$payloads = $script | python -X utf8 - $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not serialize schema fixtures' }
foreach ($payload in $payloads) {
    if (!($payload | Test-Json -SchemaFile $schema)) { throw 'N2E schema validation failed' }
}
Write-Output "Validated $($payloads.Count) JSON payloads"
