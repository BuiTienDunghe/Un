# .scratch — issue tracker của repo

Đây là issue tracker cho repo này, theo cấu hình `/setup-matt-pocock-skills`.
Spec và ticket là file markdown ở đây, **không** dùng GitHub Issues.

Quy ước đầy đủ: `docs/agents/issue-tracker.md`.

## Bố cục

```
.scratch/
└── <feature-slug>/
    ├── spec.md                    ← /to-spec ghi ra đây
    └── issues/
        ├── 01-<slug>.md           ← /to-tickets ghi ra đây, mỗi ticket một file
        └── 02-<slug>.md
```

## Thư mục này ĐƯỢC commit — có chủ đích

Repo `Un` là public và `.gitignore` cố tình chặn `.claude/` để không đẩy dữ liệu phiên
làm việc của AI lên. `.scratch/` thì ngược lại: đây là spec và ticket của dự án, là tài
liệu thật, và cần sống sót qua `git clone` mới cũng như qua các session Claude Code chạy
trên container ephemeral — không commit là mất trắng.

Đừng thêm `.scratch/` vào `.gitignore`. Nếu có thứ gì thực sự nhạy cảm, đừng viết nó vào
ticket ngay từ đầu.
