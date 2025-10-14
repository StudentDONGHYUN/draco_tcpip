# 제어 평면 규약

제어 평면은 기존 TCP 프레이밍(`net.protocol`)을 확장하여 서버에서 클라이언트로 자율주행 메타데이터를 전달하는 세 가지 새로운 메시지 종류를 추가합니다. 프레이밍(magic/version/length/kind/seq)은 변경되지 않으며, 새로운 종류는 `kind` 문자열에만 추가됩니다:

| Kind      | 용도                    | 페이로드 인코딩                               |
|-----------|------------------------|-----------------------------------------------|
| `pose`    | 로봇 자세 추정         | 바이너리 구조체(기본값) 또는 JSON             |
| `path`    | 계획된 궤적           | 크기 제한된 배열을 가진 바이너리 구조체 또는 JSON |
| `twist`   | 속도 명령             | 바이너리 구조체 또는 JSON                      |

바이너리 페이로드는 제로카피 파싱을 위해 네트워크 바이트 순서와 고정 크기를 사용합니다.
문자열은 `\0`으로 패딩되고 64바이트에서 잘립니다. JSON 페이로드는 동일한 필드를 미러링하며,
서버 노드가 `downlink_protocol` 파라미터를 `json`으로 설정하거나 불리언 `downlink_json` 
파라미터를 토글할 때 생성됩니다.

## 구조체

모든 타임스탬프는 UNIX 에포크 이후의 부호 없는 나노초를 사용합니다.

### Pose (`pose`)

```
struct PosePayload {
    uint64 stamp_ns;
    char frame_id[64];
    double x, y, z;
    double qx, qy, qz, qw;
};
```

### Twist (`twist`)

```
struct TwistPayload {
    uint64 stamp_ns;
    float vx, vy, vz;
    float wx, wy, wz;
};
```

### Path (`path`)

```
struct PathPayload {
    uint64 stamp_ns;
    char frame_id[64];
    uint16 count;  // 0 <= count <= 200
    Pose poses[count];
};

struct Pose {
    double x, y, z;
    double qx, qy, qz, qw;
};
```

경로 포즈 수는 대역폭을 제한하기 위해 200개(~33 kiB 페이로드)로 제한됩니다.

## 타이밍과 활성 상태

* 다운링크 속도는 `downlink_rate` 파라미터로 제한됩니다(기본값 10 Hz).
* 클라이언트는 `heartbeat_interval` 초마다(기본값 1초) 하트비트(`heartbeat` 종류, 빈 페이로드)를 
  전송합니다. 이 간격의 2배 동안 하트비트가 관찰되지 않으면 서버는 다운링크를 중단합니다.
* 레거시 PLY 응답은 `legacy_downlink` 파라미터 뒤에 유지됩니다. 레거시 모드가 비활성화되면 
  서버는 업로드에 대해 `ack` 메시지로 응답합니다.

## 오류 처리

* 바이너리 페이로드 크기 또는 `count` 위반 시 `ValueError`가 발생하고 메시지가 
  삭제됩니다.
* JSON 디코딩 오류는 로그로 기록되고 건너뜁니다.
* 하트비트 손실 시 다운링크는 일시 중단되지만 업링크 세션은 중단되지 않습니다. 하트비트가 
  재개되면 최신 자율주행 번들이 전송됩니다.
