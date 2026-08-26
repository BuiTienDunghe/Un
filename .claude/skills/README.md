# Agent skills (vendored)

Skill của **Matt Pocock** — <https://github.com/mattpocock/skills> (MIT, © 2026 Matt Pocock).

Được copy thủ công vào repo (không phải plugin), nên bạn **sửa trực tiếp được** — đúng
triết lý "hack around with them, make them your own" của repo gốc.

## Nguồn

| | |
|---|---|
| Repo | `mattpocock/skills` |
| Commit | `6654f6b60cd9d5be8b54c6fafe44346dabeb3b76` |
| Ngày commit | 2026-08-24 |
| Vendored | 2026-08-26 |

## Skill đã cài (9)

Tầng A — bắt buộc (8), từ `skills/engineering/`:

| Skill | Dùng để |
|---|---|
| `setup-matt-pocock-skills` | Cấu hình repo 1 lần: issue tracker, triage label, layout docs |
| `grill-with-docs` | Phỏng vấn ép buộc để làm sắc plan/design, đồng thời sinh ADR + glossary |
| `domain-modeling` | Xây và mài domain model (`CONTEXT.md`, ADR) |
| `to-spec` | Biến hội thoại hiện tại thành spec, đẩy lên issue tracker |
| `to-tickets` | Chẻ plan/spec thành ticket tracer-bullet có khai báo quan hệ blocking |
| `implement` | Triển khai theo spec/ticket |
| `tdd` | Test-driven development: vòng red → green → refactor |
| `code-review` | Review diff theo 2 trục Standards + Spec, chạy sub-agent song song |

Dependency kéo theo (1), từ `skills/productivity/`:

| Skill | Lý do |
|---|---|
| `grilling` | `grill-with-docs` là wrapper 1 dòng gọi `grilling` + `domain-modeling`. Thiếu nó thì `grill-with-docs` gãy. |

## Đã lược bỏ so với repo gốc

- **`agents/openai.yaml`** trong mỗi skill — file cấu hình dành cho Codex/OpenAI, Claude Code
  không đọc. Cài lại nếu bạn dùng thêm agent khác.
- **16 skill còn lại** của repo gốc (`ask-matt`, `triage`, `diagnosing-bugs`, `wayfinder`,
  `codebase-design`, `research`, `prototype`, `handoff`, `teach`, …). Thêm sau bằng cách copy
  thư mục tương ứng vào đây.

### Hệ quả cần biết

- `triage` **chưa cài** → `setup-matt-pocock-skills` sẽ tự bỏ qua Section B (triage labels)
  và không sinh `docs/agents/triage-labels.md`. Đây là hành vi có chủ đích của skill, không phải lỗi.
- `codebase-design` **chưa cài** → `tdd` vẫn chạy bình thường; nó chỉ gọi `codebase-design`
  như từ điển thuật ngữ khi cần bàn sâu về module/seam/interface.
- `code-review` **trùng tên** với skill `/code-review` có sẵn của Claude Code. Bản trong thư mục
  này (cấp project) được ưu tiên. Hai skill làm việc khác nhau: bản Matt review theo
  Standards + Spec, bản built-in soi bug correctness và cleanup.

## Cập nhật lên bản mới

```bash
git clone --depth 1 https://github.com/mattpocock/skills.git /tmp/mp-skills
for k in setup-matt-pocock-skills grill-with-docs domain-modeling to-spec \
         to-tickets implement tdd code-review; do
  rm -rf ".claude/skills/$k"
  cp -r "/tmp/mp-skills/skills/engineering/$k" ".claude/skills/$k"
done
rm -rf .claude/skills/grilling
cp -r /tmp/mp-skills/skills/productivity/grilling .claude/skills/grilling
find .claude/skills -type d -name agents -exec rm -rf {} +
```

Rồi xem `git diff` để giữ lại phần bạn đã tự sửa.
