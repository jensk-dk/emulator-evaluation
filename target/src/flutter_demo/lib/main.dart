// Flutter graphics workload for the emulator evaluation.
//
// Shows a fixed animated scene full screen: a painted background with 64
// spinning translucent shapes, under a grid of 24 widgets with text that are
// rebuilt and laid out every frame. The animation advances by frame number.
// Flutter draws one frame per display refresh, so unlike the other graphics
// tests the frame rate here is bounded by the display's refresh rate; the
// build and raster times show how much of each refresh interval was used.
//
// The marker blocks match target/src/emugfx.c: four corners and one at the
// top centre in this technology's colour, so the launcher can check a capture
// of the display.
//
// Environment: EMU_GFX_SECONDS (measuring time), EMU_GFX_HOLD (how long the
// last frame stays up for a capture), EMU_GFX_RENDERER and
// EMU_GFX_ACCELERATED (the display's OpenGL ES renderer, passed through to
// the result).
//
// Output: one "EMU-RESULT:" line, and with a hold time an "EMU-SCREEN:" line.
//
// With EMU_VIDEO_SOURCE set the application shows decoded video instead: see
// video.dart.
import 'dart:async';
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';

import 'video.dart';

const List<int> kMarker = <int>[255, 0, 128];
const int kShapes = 64;
const int kColumns = 6;
const int kRows = 4;

double _environmentSeconds(String name, double fallback) {
  final double? value = double.tryParse(Platform.environment[name] ?? '');
  return value == null || value < 0 ? fallback : value;
}

void main() {
  // The media-decode workload uses the application to show decoded video.
  final String? video = Platform.environment['EMU_VIDEO_SOURCE'];
  if (video != null && video.isNotEmpty) {
    runApp(VideoApp(source: video));
    return;
  }
  final int started = developer.Timeline.now;
  runApp(DemoApp(startedMicroseconds: started));
}

class DemoApp extends StatefulWidget {
  const DemoApp({super.key, required this.startedMicroseconds});

  final int startedMicroseconds;

  @override
  State<DemoApp> createState() => _DemoAppState();
}

class _DemoAppState extends State<DemoApp> with SingleTickerProviderStateMixin {
  late final Ticker _ticker;
  final List<FrameTiming> _timings = <FrameTiming>[];
  final double _seconds = _environmentSeconds('EMU_GFX_SECONDS', 5);
  final double _hold = _environmentSeconds('EMU_GFX_HOLD', 0);
  int _frame = 0;
  bool _finished = false;

  @override
  void initState() {
    super.initState();
    SchedulerBinding.instance.addTimingsCallback(_onTimings);
    _ticker = createTicker((Duration _) {
      if (!_finished) {
        setState(() => _frame++);
      }
    })
      ..start();
  }

  @override
  void dispose() {
    _ticker.dispose();
    super.dispose();
  }

  void _onTimings(List<FrameTiming> timings) {
    if (_finished) {
      return;
    }
    _timings.addAll(timings);
    final int first = _timings.first.timestampInMicroseconds(ui.FramePhase.rasterFinish);
    final int last = _timings.last.timestampInMicroseconds(ui.FramePhase.rasterFinish);
    if (_timings.length >= 3 && (last - first) / 1e6 >= _seconds) {
      _finished = true;
      _ticker.stop();
      unawaited(_finish());
    }
  }

  static double _percentile(List<double> sorted, double fraction) {
    final int index = (fraction * sorted.length).ceil() - 1;
    return sorted[index.clamp(0, sorted.length - 1)];
  }

  static Map<String, double> _summary(List<double> values) {
    final List<double> sorted = List<double>.of(values)..sort();
    final double mean = sorted.reduce((double a, double b) => a + b) / sorted.length;
    double round(double v) => (v * 1000).roundToDouble() / 1000;
    return <String, double>{
      'mean': round(mean),
      'p50': round(_percentile(sorted, 0.50)),
      'p99': round(_percentile(sorted, 0.99)),
      'max': round(sorted.last),
    };
  }

  Future<void> _finish() async {
    final List<int> finished = <int>[
      for (final FrameTiming t in _timings) t.timestampInMicroseconds(ui.FramePhase.rasterFinish),
    ];
    final double elapsed = (finished.last - finished.first) / 1e6;
    final int frames = finished.length - 1;
    final List<double> intervals = <double>[
      for (int i = 1; i < finished.length; i++) (finished[i] - finished[i - 1]) / 1e3,
    ];
    // The first frame includes one-off start-up work; leave it out as the
    // other graphics tests do.
    final List<FrameTiming> measured = _timings.sublist(1);
    final ui.Size size = ui.PlatformDispatcher.instance.views.first.physicalSize;
    final String? accelerated = Platform.environment['EMU_GFX_ACCELERATED'];
    final Map<String, Object?> result = <String, Object?>{
      'area': 'graphics',
      'test': 'flutter_fps',
      'technology': 'flutter',
      'unit': 'frames/s',
      'value': (frames / elapsed * 100).roundToDouble() / 100,
      'resolution': '${size.width.round()}x${size.height.round()}',
      'frames': frames,
      'seconds': (elapsed * 1000).roundToDouble() / 1000,
      'frame_time_ms': _summary(intervals),
      'build_time_ms': _summary(<double>[
        for (final FrameTiming t in measured) t.buildDuration.inMicroseconds / 1e3,
      ]),
      'raster_time_ms': _summary(<double>[
        for (final FrameTiming t in measured) t.rasterDuration.inMicroseconds / 1e3,
      ]),
      'first_frame_seconds': ((finished.first - widget.startedMicroseconds) / 1e3).roundToDouble() / 1e3,
      'paced_by_display': true,
      'renderer': Platform.environment['EMU_GFX_RENDERER'],
      'api': 'Flutter ${Platform.environment['EMU_FLUTTER_VERSION'] ?? ''}, Dart ${Platform.version.split(' ').first}',
      'accelerated': accelerated == null ? null : accelerated == 'true',
    };
    stdout.writeln('EMU-RESULT: ${jsonEncode(result)}');
    await stdout.flush();
    if (_hold > 0) {
      // Let the last frame reach the display before announcing it.
      await Future<void>.delayed(const Duration(milliseconds: 1500));
      stdout.writeln('EMU-SCREEN: ${jsonEncode(<String, Object?>{
            'test': 'flutter_fps',
            'technology': 'flutter',
            'width': size.width.round(),
            'height': size.height.round(),
            'marker': kMarker,
            'on_display': null,
          })}');
      await stdout.flush();
      await Future<void>.delayed(Duration(milliseconds: (_hold * 1000).round()));
    }
    await stdout.flush();
    exit(0);
  }

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.ltr,
      child: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final double scale = constraints.maxHeight / 1080;
          return CustomPaint(
            painter: _ScenePainter(_frame),
            foregroundPainter: const _MarkerPainter(),
            child: Padding(
              padding: EdgeInsets.symmetric(horizontal: 60 * scale, vertical: 110 * scale),
              child: Column(
                children: <Widget>[
                  for (int row = 0; row < kRows; row++)
                    Expanded(
                      child: Row(
                        children: <Widget>[
                          for (int column = 0; column < kColumns; column++)
                            Expanded(child: _Card(index: row * kColumns + column, frame: _frame, scale: scale)),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _Card extends StatelessWidget {
  const _Card({required this.index, required this.frame, required this.scale});

  final int index;
  final int frame;
  final double scale;

  @override
  Widget build(BuildContext context) {
    final double t = frame * 0.02;
    final double progress = 0.5 + 0.5 * math.sin(t * (1 + index % 3) + index);
    final double hue = ((index * 37 + frame) % 360).toDouble();
    return Padding(
      padding: EdgeInsets.all(8 * scale),
      child: Transform.rotate(
        angle: 0.06 * math.sin(t * 2 + index),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: HSVColor.fromAHSV(0.8, hue, 0.55, 0.95).toColor(),
            borderRadius: BorderRadius.circular(16 * scale),
            border: Border.all(color: const Color(0xCCFFFFFF), width: 2 * scale),
          ),
          child: Padding(
            padding: EdgeInsets.all(12 * scale),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  'Channel ${index + 1}',
                  maxLines: 1,
                  overflow: TextOverflow.clip,
                  style: TextStyle(
                    color: const Color(0xFF101418),
                    fontSize: 26 * scale,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                Text(
                  'Frame $frame',
                  maxLines: 1,
                  overflow: TextOverflow.clip,
                  style: TextStyle(color: const Color(0xFF202830), fontSize: 18 * scale),
                ),
                ClipRRect(
                  borderRadius: BorderRadius.circular(5 * scale),
                  child: SizedBox(
                    height: 10 * scale,
                    child: ColoredBox(
                      color: const Color(0x55000000),
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: FractionallySizedBox(
                          widthFactor: progress,
                          heightFactor: 1,
                          child: const ColoredBox(color: Color(0xFFFFFFFF)),
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ScenePainter extends CustomPainter {
  const _ScenePainter(this.frame);

  final int frame;

  @override
  void paint(Canvas canvas, Size size) {
    final double t = frame * 0.02;
    final Rect area = Offset.zero & size;
    final Color top = HSVColor.fromAHSV(1, (frame * 0.5) % 360, 0.7, 0.9).toColor();
    final Color bottom = HSVColor.fromAHSV(1, (frame * 0.5 + 120) % 360, 0.7, 0.5).toColor();
    canvas.drawRect(
      area,
      Paint()..shader = ui.Gradient.linear(area.topLeft, area.bottomRight, <Color>[top, bottom]),
    );
    final Paint paint = Paint();
    for (int i = 0; i < kShapes; i++) {
      final double cx = (0.5 + 0.41 * math.sin(t * (0.5 + 0.5 * (i % 4)) + i * 0.7)) * size.width;
      final double cy = (0.5 + 0.35 * math.cos(t * (0.5 + 0.5 * ((i ~/ 4) % 3)) + i * 1.3)) * size.height;
      final double side = (0.05 + 0.02 * (i % 3)) * size.height;
      paint.color = Color.fromARGB(
        153,
        (127.5 + 127.5 * math.sin(i * 0.9)).round(),
        (127.5 + 127.5 * math.sin(i * 1.7 + 2.0)).round(),
        (127.5 + 127.5 * math.sin(i * 2.3 + 4.0)).round(),
      );
      canvas.save();
      canvas.translate(cx, cy);
      canvas.rotate(t * (1 + i % 5) + i);
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromCenter(center: Offset.zero, width: side, height: side),
          Radius.circular(side * 0.15),
        ),
        paint,
      );
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(_ScenePainter oldDelegate) => oldDelegate.frame != frame;
}

class _MarkerPainter extends CustomPainter {
  const _MarkerPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final double s = (size.height / 12).floorToDouble();
    final double centre = (size.width / 2).floorToDouble();
    final Paint paint = Paint()..isAntiAlias = false;
    void block(Rect rect, Color color) {
      paint.color = color;
      canvas.drawRect(rect, paint);
    }

    block(Rect.fromLTWH(0, 0, s, s), const Color(0xFFFF0000));
    block(Rect.fromLTWH(size.width - s, 0, s, s), const Color(0xFF00FF00));
    block(Rect.fromLTWH(0, size.height - s, s, s), const Color(0xFF0000FF));
    block(Rect.fromLTWH(size.width - s, size.height - s, s, s), const Color(0xFFFFFFFF));
    block(Rect.fromLTWH(centre - s, 0, 2 * s, s), Color.fromARGB(255, kMarker[0], kMarker[1], kMarker[2]));
  }

  @override
  bool shouldRepaint(_MarkerPainter oldDelegate) => false;
}
