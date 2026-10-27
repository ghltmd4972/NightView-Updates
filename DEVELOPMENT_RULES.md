# AnimePicker Development Rules

## Temporary script cleanup gate

Any temporary PowerShell or shell script created for build, install, verification, inspection, migration, publishing, or debugging is disposable.

Required workflow:
1. Create temporary scripts only when needed.
2. Run the intended build/install/verification task.
3. Confirm the final artifact or installed state.
4. Delete every temporary script created for that task before reporting completion.
5. Run a final check of the temporary working location and confirm no temporary `.ps1`/helper scripts remain.

A task is not considered complete while temporary test/install/inspection scripts are left in the user's Downloads folder or other user-facing folders.

Do not delete permanent project scripts that are intentionally part of the repository or product.

## Canonical desktop entry and update-only workflow

- **Single canonical main-PC desktop entry:** `C:\Users\PC\Desktop\애니 캐릭터 랜덤 추첨기.lnk` (display name: **애니 캐릭터 랜덤 추첨기**).
- Its target MUST remain the existing auto-updating launcher: `C:\Users\PC\Desktop\Anime Character Random Picker\AnimePickerLauncher.exe`.
- **Do not create a new independent app or alternative EXE/launcher, side-by-side variant, or competing desktop shortcut** for any normal feature, bug fix, or UI change. The user launches the *same desktop shortcut* after every update.
- Make changes in the **existing** `anime-picker-updates` branch (principally `native/Program.cs`, `native/NativeHttpServer.cs`, and `native/picker.html`). Do not mix changes into NightView's `main` branch.
- Increment the existing AnimePicker version and publish through `.github/workflows/anime-picker-core.yml` into `releases/<version>/AnimePickerCore.exe`, with matching SHA-256/size and `latest.json`. The launcher automatically downloads the new core; keep the launcher entry path stable.
- Before claiming completion, verify the GitHub build and release manifest, run the *existing launcher* to obtain the update, test the affected features and reopening/session-state regression, and verify the desktop shortcut still targets that launcher.
- Preserve the linked character/expression text files and persistent state. Do not delete prior binaries, data, shortcuts, or backups without explicit authorization. Avoid leaving disposable test artifacts.
