# Screen casting: browser, SRT, Google Cast, DLNA and Miracast

Four independent ways to show the phone/desktop screen elsewhere, all driven by one
helper (`s9-cast`) and one tray menu.

## Capture and encoding
`mirscreencast` (from the Mir tools) captures the physical screen (RGBA 1920x1080@60) and is
piped into `ffmpeg` (x264 `ultrafast zerolatency`, no B-frames - the result is Constrained
Baseline, so decoders must read the codec string from the stream instead of assuming it).
Audio is taken from a PulseAudio *null sink* ("Screen Cast"); while casting, the phone itself
is muted and sound goes only to the destination. `s9-cast-audio restore` undoes it.

PulseAudio 16 here rejects `sink_properties=device.description="Screen Cast"`; the form that
works is `sink_properties="device.description='Screen Cast'"`. The real Pulse runs in a private
mount namespace, so tools must enter it with `nsenter -t <pulse pid> -m`.

## Modes
| Mode | How |
|---|---|
| **Web browser** | the phone serves an MSE page (`/v/<token>/`) with fragmented MP4 (0.5 s fragments); any browser on the LAN can watch, ~1 s latency; stops after 5 min with no viewer |
| **SRT** | encrypted `srt://` listener for VLC/ffplay on a PC |
| **Google Cast / DLNA** | hand-written Cast v2 (TLS 8009 + protobuf) and DLNA AVTransport SOAP; discovery by mDNS `_googlecast._tcp` and SSDP |
| **Miracast (Wi-Fi Direct)** | own RTSP *source* server + `rtp_mpegts` over a P2P group (below) |

### Audio/video sync on TVs
TVs decode video later than audio. A configurable "delay sound" (`av_offset`, ms, positive
delays audio) fixes it; 300 ms was right for the tested TV. Implementation detail:
`-itsoffset` with a positive value is silently dropped for fragmented MP4, so use the
`adelay=N|N` filter (quote it when the command is built as a shell string).

## Miracast lessons (the non-obvious part)
* The **sink connects by TCP to the source's port** (7236, advertised in the WFD IE); the
  source is the RTSP server and speaks first (M1 OPTIONS). Connecting out to the sink's port
  is the wrong direction.
* Message flow: M1 OPTIONS, M2 (sink), M3 GET_PARAMETER, M4 SET_PARAMETER (video formats,
  `wfd_audio_codecs: AAC 00000001 00` - audio is mandatory, `wfd_content_protection: none`,
  presentation URL, client RTP ports), M5 trigger SETUP, SETUP, PLAY, keep-alives, TEARDOWN.
* MPEG-TS PIDs matter. FFmpeg's `rtp_mpegts` muxer **ignores** loose `-mpegts_*` options; use
  `-streamid 0:4113 -streamid 1:4352` and `-mpegts_muxer_options mpegts_pmt_start_pid=256:pcr_period=40`
  so PMT=0x100, video=0x1011, audio=0x1100. A TV that stays black while its RTCP reports show
  packets arriving is almost always wrong PIDs; check with a local capture.
* Wi-Fi Direct needs the soft-AP interface down and unmanaged, and the group must be created
  **by NetworkManager** (a `wifi-p2p` connection via libnm); a group created with `wpa_cli`
  is removed by NetworkManager within ~0.1 s. Marking the P2P interfaces that NetworkManager creates (`p2p-dev-wlan0`,
  `p2p-wlan0-*`) `unmanaged` does not help. (Not to be confused with the driver's own `p2p0` netdev, which Miracast does not
  use and which the image does keep unmanaged, to avoid a pointless "Wired connection 1": see
  [`tools/image/README.md`](../tools/image/README.md).)
* After boot the P2P device may not come up (`Could not set interface 'p2p-dev-swlan0' UP`).
  A one-shot unit 25 s after boot stops the services, removes stale P2P devices and restarts
  them with the AP interface down and unmanaged. Always confirm with
  `wpa_cli -i wlan0 p2p_find 3` - NetworkManager's state and `StartFind` can report success
  without P2P.
* When the phone becomes group owner, receivers ask for DHCP by broadcast for ~25 s and give up,
  so the phone needs `192.168.49.1/24` (the standard Wi-Fi Direct subnet) plus its own tiny DHCP server. <!-- privacy-ok -->
* Open: remote input from the sink back to the phone (UIBC) and keeping groups alive past 30 s.
