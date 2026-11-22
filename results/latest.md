| case | category | domain | expected | decision | ok | latency | pages |
|---|---|---|---|---|---|---|---|
| browserbase_stale | stale | browserbase.com | BLOCK | BLOCK | yes | 5.7s | 11 |
| clerk_stale | stale | clerk.com | BLOCK | BLOCK | yes | 46.9s | 10 |
| e2b_correct | all-correct | e2b.dev | PASS | PASS | yes | 20.5s | 9 |
| encord_stale | stale | encord.com | BLOCK | BLOCK | yes | 87.9s | 5 |
| inngest_unverifiable | unverifiable | inngest.com | REVIEW | REVIEW | yes | 7.1s | 10 |
| mintlify_tricky | tricky | mintlify.com | BLOCK | BLOCK | yes | 42.7s | 9 |
| modal_stale | stale | modal.com | BLOCK | BLOCK | yes | 71.3s | 9 |
| resend_correct | all-correct | resend.com | PASS | PASS | yes | 33.6s | 11 |
| trigger_correct | all-correct | trigger.dev | PASS | PASS | yes | 28.6s | 9 |
| warp_unverifiable | unverifiable | warp.dev | REVIEW | REVIEW | yes | 28.1s | 10 |

```json
{
  "decision_accuracy": "10/10",
  "stale_precision": 1.0,
  "stale_recall": 1.0,
  "tp": 5,
  "fp": 0,
  "fn": 0,
  "median_latency_ms": 31073,
  "median_pages": 9.5
}
```
