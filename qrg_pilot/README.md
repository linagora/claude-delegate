# QRG pilot zones

Everything under this directory is **fictitious**. It gives the QRG router (`qrg-router`) one zone per
sensitivity class to route against, declared in [`.linagora/sensitivity.yml`](../.linagora/sensitivity.yml).
No real client, person, system or secret appears here.

| Directory | Class | Stands for |
|---|---|---|
| `c0_public/` | C0 public | Code already published |
| `c1_internal/` | C1 internal | Unpublished internal tooling |
| `c2_client_acme/` | C2 client confidential | Code of a client under a public procurement contract (ACME is fictitious) |
| `c3_secnumcloud/` | C3 sensitive | A SecNumCloud scope, synthetic personal data and a fake secret |

The rest of the repository is C0, the file's default.

## Canaries

Each zone above C0 carries a unique canary string in its own module, which may only reach the models its class admits:

| Zone | Canary in | Must never reach |
|---|---|---|
| `c1_internal/` | `changelog.py` | An API without a contract |
| `c2_client_acme/` | `invoice.py` | A model neither hosted by LINAGORA nor under an EU contract |
| `c3_secnumcloud/` | `pseudonymize.py` | A model not hosted by LINAGORA |

The values never appear outside their zone: this README is C0, so a canary written here would leave with every export. The end-to-end scenarios search the gateway journal and the network capture for them.

## Tests

```bash
python3 -m unittest discover -s qrg_pilot -t .
```
