# NightView Updates

NightView의 공식 공개 업데이트 채널입니다.

NightView는 `latest.json`을 확인하고, 새 버전이 활성화되어 있을 때만 업데이트를 내려받습니다. 다운로드된 `NightView.exe`와 `NightViewUpdater.exe`는 파일 크기와 SHA-256을 확인한 뒤 사용됩니다.

배포 흐름:
1. 소스 아카이브 SHA-256 검증
2. Linux에서 gofmt / go test / race detector / go vet
3. Windows에서 실제 릴리스 후보 빌드
4. Windows 네이티브 업데이트 교체 및 실패 롤백 테스트
5. 모든 검증이 성공한 경우에만 `releases/<version>/`과 `latest.json` 게시

`latest.json.enabled`가 `false`이면 NightView는 해당 버전을 자동 설치하지 않습니다.
