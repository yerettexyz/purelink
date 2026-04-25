# 🔗 Purelink v1.0.0

Purelink is a high-performance Discord bot designed for professional link purification. It automates the process of identifying, unwrapping, and cleaning tracking links to ensure a private and aesthetic conversation experience.

### 🚀 Highlights:
*   **Massive Link Coverage**: Engineered with a blocklist of over **3,500 tracking and ad domains** (via `data.json`).
*   **Multi-Hop Smart Unwrapper**: Surgically jumps through complex redirect chains (e.g., Bitly -> Mavely -> CJ Affiliate) using a hybrid of `curl` headers and **Smart Peeking** to bypass bot protections.
*   **Surgical Scrubbing**: Strips invasive tracking parameters (`utm_`, `cjevent`, `xcm_`, etc.) while intelligently preserving functional search parameters.
*   **Webhook Reposting**: Seamlessly deletes "dirty" messages and reposts cleaned versions using the original user's name and avatar.
*   **Production Hardened**: Full security audit implemented. Protected against SSRF, MITM, and DoS attacks with pinned dependencies and absolute configuration paths.

### ✅ Mavely Resolution:
*   **Fixed**: Purelink now successfully resolves `mavely.link` and `mavelylife.com` links. By utilizing **Smart Peeking**, the bot identifies the destination URL hidden within the affiliate jump-link, bypassing Cloudflare's 403 Forbidden blocks and delivering the final store page.

---
*Clean links. Better privacy. Purelink.*
