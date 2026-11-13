// Video mode of the Flutter workload: decoded video drawn by a Flutter
// application, for the media-decode workload.
//
// Decoded frames (RGBA, one after another) come from the file named by
// EMU_VIDEO_SOURCE, which the workload connects to a decoder that delivers
// them in real time. A second isolate reads them, so that reading keeps up
// with the decoder however long drawing takes. The application asks that
// isolate for a frame whenever it is ready to draw one and gets the newest;
// a frame that was replaced by a newer one before the application asked is
// never shown, and counts as dropped. So a display that draws slower than
// the stream's frame rate drops frames instead of slowing the stream down.
//
// Environment: EMU_VIDEO_SOURCE, EMU_VIDEO_WIDTH, EMU_VIDEO_HEIGHT,
// EMU_VIDEO_FRAMES (how many frames the stream has), EMU_GFX_HOLD (how long
// the last frame stays up for a capture).
//
// Output: one "EMU-VIDEO:" line when the stream has ended and its last frame
// is on the display.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';

int _environmentInt(String name, int fallback) => int.tryParse(Platform.environment[name] ?? '') ?? fallback;

class VideoApp extends StatefulWidget {
  const VideoApp({super.key, required this.source});

  final String source;

  @override
  State<VideoApp> createState() => _VideoAppState();
}

/// The reading isolate. Messages to the application: a [SendPort] to ask on,
/// then for each request `[index, pixels]` with the newest frame, and at the
/// end of the stream `[received, replaced, microseconds]`.
Future<void> _reader(List<Object> setup) async {
  final SendPort application = setup[0] as SendPort;
  final String source = setup[1] as String;
  final int frameBytes = setup[2] as int;
  final ReceivePort requests = ReceivePort();
  application.send(requests.sendPort);

  int received = 0;
  int replaced = 0;
  Uint8List? newest;
  int newestIndex = -1;
  bool wanted = false;
  void hand() {
    final Uint8List? pixels = newest;
    if (wanted && pixels != null) {
      application.send(<Object>[newestIndex, TransferableTypedData.fromList(<Uint8List>[pixels])]);
      newest = null;
      wanted = false;
    }
  }

  requests.listen((Object? _) {
    wanted = true;
    hand();
  });

  final Stopwatch clock = Stopwatch();
  int lastArrival = 0;
  try {
    final RandomAccessFile file = File(source).openSync();
    while (true) {
      final Uint8List frame = Uint8List(frameBytes);
      int filled = 0;
      while (filled < frameBytes) {
        final int count = file.readIntoSync(frame, filled, frameBytes);
        if (count <= 0) {
          break;
        }
        filled += count;
      }
      if (filled < frameBytes) {
        break;
      }
      if (!clock.isRunning) {
        clock.start();
      }
      lastArrival = clock.elapsedMicroseconds;
      if (newest != null) {
        replaced++;
      }
      newest = frame;
      newestIndex = received++;
      hand();
      // Let a request that came in while reading be answered.
      await Future<void>.delayed(Duration.zero);
    }
    file.closeSync();
  } on FileSystemException {
    // The decoder went away; report what was read.
  }
  // The last frame is always shown: wait for it to be asked for.
  while (newest != null) {
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  application.send(<int>[received, replaced, lastArrival]);
  requests.close();
}

class _VideoAppState extends State<VideoApp> {
  final int _width = _environmentInt('EMU_VIDEO_WIDTH', 1280);
  final int _height = _environmentInt('EMU_VIDEO_HEIGHT', 720);
  final int _expected = _environmentInt('EMU_VIDEO_FRAMES', 0);
  final double _hold = double.tryParse(Platform.environment['EMU_GFX_HOLD'] ?? '') ?? 0;
  final Set<int> _painted = <int>{};
  final ReceivePort _frames = ReceivePort();

  SendPort? _requests;
  ui.Image? _image;
  int _imageIndex = -1;
  int _received = 0;
  int _replaced = 0;
  bool _preparing = false;
  bool _ended = false;
  bool _finishing = false;
  int _lastArrival = 0;

  @override
  void initState() {
    super.initState();
    _frames.listen(_onMessage);
    unawaited(Isolate.spawn(_reader, <Object>[_frames.sendPort, widget.source, _width * _height * 4]));
  }

  void _onMessage(Object? message) {
    if (message is SendPort) {
      _requests = message;
      message.send(null);
    } else if (message is List<int>) {
      _received = message[0];
      _replaced = message[1];
      _lastArrival = message[2];
      _ended = true;
      _maybeFinish();
    } else if (message is List<Object>) {
      final Uint8List pixels = (message[1] as TransferableTypedData).materialize().asUint8List();
      _prepare(pixels, message[0] as int);
    }
  }

  void _prepare(Uint8List pixels, int index) {
    _preparing = true;
    ui.decodeImageFromPixels(pixels, _width, _height, ui.PixelFormat.rgba8888, (ui.Image image) {
      setState(() {
        _image?.dispose();
        _image = image;
        _imageIndex = index;
      });
      // Ask for the next frame once this one has been drawn.
      SchedulerBinding.instance.addPostFrameCallback((Duration _) {
        _preparing = false;
        _requests?.send(null);
        _maybeFinish();
      });
    });
  }

  void _maybeFinish() {
    if (!_ended || _preparing || _finishing) {
      return;
    }
    _finishing = true;
    // After the frame that paints the last image.
    SchedulerBinding.instance.addPostFrameCallback((Duration _) => unawaited(_finish()));
    SchedulerBinding.instance.scheduleFrame();
  }

  Future<void> _finish() async {
    // Let that frame reach the display before announcing it.
    await Future<void>.delayed(const Duration(milliseconds: 500));
    final ui.Size size = ui.PlatformDispatcher.instance.views.first.physicalSize;
    final int presented = _painted.length;
    final int expected = _expected > 0 ? _expected : _received;
    stdout.writeln('EMU-VIDEO: ${jsonEncode(<String, Object?>{
          'dropped': math.max(0, expected - presented),
          'frames_received': _received,
          'frames_presented': presented,
          'replaced_before_drawing': _replaced,
          'seconds': (_lastArrival / 1e3).roundToDouble() / 1e3,
          'window': '${size.width.round()}x${size.height.round()}',
        })}');
    await stdout.flush();
    if (_hold > 0) {
      await Future<void>.delayed(Duration(milliseconds: (_hold * 1000).round()));
    }
    exit(0);
  }

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _VideoPainter(_image, _imageIndex, _painted),
      child: const SizedBox.expand(),
    );
  }
}

class _VideoPainter extends CustomPainter {
  _VideoPainter(this.image, this.index, this.painted);

  final ui.Image? image;
  final int index;
  final Set<int> painted;

  @override
  void paint(Canvas canvas, Size size) {
    final ui.Image? frame = image;
    if (frame == null) {
      canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFF000000));
      return;
    }
    canvas.drawImageRect(
      frame,
      Rect.fromLTWH(0, 0, frame.width.toDouble(), frame.height.toDouble()),
      Offset.zero & size,
      Paint()..filterQuality = FilterQuality.low,
    );
    painted.add(index);
  }

  @override
  bool shouldRepaint(_VideoPainter oldDelegate) => oldDelegate.index != index;
}
