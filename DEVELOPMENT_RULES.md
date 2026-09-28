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
