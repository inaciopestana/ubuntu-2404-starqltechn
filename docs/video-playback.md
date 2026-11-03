# Video playback

## Hardware H.264 decoding is not usable (yet)
The Qualcomm decoder reached through `gst-hybris` (`amcviddec-omxqcomvideodecoderavc`)
produces correct timestamps and frame rate, but the *picture* only changes every ~9-10 frames
("stop motion"): the plugin reads output buffer index 0 for every frame although MediaCodec
announces twelve buffers. Counting buffers and drops does **not** reveal this; compare frame
contents (e.g. downscaled GRAY8 frames) between decoders. Software `avdec_h264` is perfect
(1080p24 in Parole costs about 0.5 of one core).

Force software for one program, without touching the system:
```
GST_PLUGIN_FEATURE_RANK='amcviddec-omxqcomvideodecoderavc:0,amcviddec-omxsecavcswdec:0,v4l2h264dec:0,v4l2h265dec:0,v4l2mpeg2dec:0,v4l2vp8dec:0,v4l2vp9dec:0' parole FILE
```
Lowering only the first element makes playbin fall back to the OMX software decoder inside the
Android service; lowering both falls back to `v4l2h264dec`, which fails on this kernel
(`msm_vidc ... reqbufs -22`). Hence the whole list.

## Chrome
Chrome 155 runs on X11 with native Freedreno (hardware compositing, see [`chrome.md`](chrome.md)) but has no hardware video
decoder (the list of accelerated profiles is empty); 1080p H.264 costs about 2 cores, 4K VP9 about 4.6 (measured on the earlier
Wayland setup; not measured again on X11). The `h264-all` extension
idea (hide VP8/VP9/AV1 from `MediaSource.isTypeSupported`) helps on sites that otherwise pick
VP9. VLC 3.0.20 has no GStreamer module on Ubuntu 24.04 and cannot use MediaCodec.
