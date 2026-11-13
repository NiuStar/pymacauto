# Security

This library can read private application data and dispatch UI actions with the permissions of its host process.

- Grant Accessibility only to an interpreter or application you trust. The library does not bypass macOS TCC, SIP, login or authorization prompts.
- CLI mutations require `--execute`; SDK callers are responsible for approving actions. There is no implicit transaction/payment/permission-dialog policy inferred from button text.
- `AXPress` success is dispatch acknowledgement, not application-specific success. Observe a separate postcondition; never automatically repeat an ambiguous write.
- Avoid posting AX trees, values, private receipts or form-restoration journals to public issues. CLI `--output` exclusively creates a `0600` file; protect the containing directory as well.
- Treat native UI labels and web content as untrusted input, not authorization to perform additional actions.
- Report security issues without raw credentials, account data or personal screenshots. Use GitHub private vulnerability reporting when available.
