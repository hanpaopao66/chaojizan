import 'package:flutter/painting.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/src/utils/scan_window_utils.dart';

void main() {
  group('calculateBoxFitRatio', () {
    const cameraPreviewSize = Size(480, 640);
    const size = Size(432, 256);

    test('works with BoxFit.fill', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: cameraPreviewSize,
        size: size,
      );

      expect(ratio, (widthRatio: 0.9, heightRatio: 0.4));
    });

    test('works with BoxFit.contain', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.contain,
        cameraPreviewSize: cameraPreviewSize,
        size: size,
      );

      expect(ratio, (widthRatio: 0.4, heightRatio: 0.4));
    });

    test('works with BoxFit.cover', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.cover,
        cameraPreviewSize: cameraPreviewSize,
        size: size,
      );

      expect(ratio, (widthRatio: 0.9, heightRatio: 0.9));
    });

    test('works with BoxFit.fitWidth', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fitWidth,
        cameraPreviewSize: cameraPreviewSize,
        size: size,
      );

      expect(ratio, (widthRatio: 0.9, heightRatio: 0.9));
    });

    test('works with BoxFit.fitHeight', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fitHeight,
        cameraPreviewSize: cameraPreviewSize,
        size: size,
      );

      expect(ratio, (widthRatio: 0.4, heightRatio: 0.4));
    });

    test('works with BoxFit.none', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.none,
        cameraPreviewSize: cameraPreviewSize,
        size: size,
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });

    test('works with BoxFit.scaleDown', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.scaleDown,
        cameraPreviewSize: cameraPreviewSize,
        size: size,
      );

      expect(ratio, (widthRatio: 0.4, heightRatio: 0.4));
    });

    test('handles zero width in camera preview size', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: const Size(0, 100),
        size: const Size(200, 200),
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });

    test('handles zero height in camera preview size', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: const Size(100, 0),
        size: const Size(200, 200),
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });

    test('handles zero camera preview size', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: Size.zero,
        size: const Size(200, 200),
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });

    test('handles zero width in target size', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: const Size(100, 100),
        size: const Size(0, 200),
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });

    test('handles zero height in target size', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: const Size(100, 100),
        size: const Size(200, 0),
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });

    test('handles zero target size', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: const Size(200, 200),
        size: Size.zero,
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });

    test('handles equal target and camera sizes', () {
      final ratio = ScanWindowUtils.calculateBoxFitRatio(
        boxFit: BoxFit.fill,
        cameraPreviewSize: const Size(200, 200),
        size: const Size(200, 200),
      );

      expect(ratio, (widthRatio: 1.0, heightRatio: 1.0));
    });
  });

  group('calculateScanWindowRelativeToTextureInPercentage', () {
    group(
      'can compute scan window for landscape widget inside portrait texture',
      () {
        const textureSize = Size(480, 640);
        const widgetSize = Size(432, 256);
        final ctx = ScanWindowTestContext(
          textureSize: textureSize,
          widgetSize: widgetSize,
          scanWindow: Rect.fromLTWH(
            widgetSize.width / 4,
            widgetSize.height / 4,
            widgetSize.width / 2,
            widgetSize.height / 2,
          ),
        );

        test('with BoxFit.none', () {
          ctx.testScanWindow(
            BoxFit.none,
            const Rect.fromLTRB(0.275, 0.4, 0.725, 0.6),
          );
        });

        test('with BoxFit.fill', () {
          ctx.testScanWindow(
            BoxFit.fill,
            const Rect.fromLTRB(0.25, 0.25, 0.75, 0.75),
          );
        });

        test('with BoxFit.fitHeight', () {
          ctx.testScanWindow(
            BoxFit.fitHeight,
            const Rect.fromLTRB(0, 0.25, 1, 0.75),
          );
        });

        test('with BoxFit.fitWidth', () {
          ctx.testScanWindow(
            BoxFit.fitWidth,
            const Rect.fromLTRB(
              0.25,
              0.38888888888888895,
              0.75,
              0.6111111111111112,
            ),
          );
        });

        test('with BoxFit.cover', () {
          ctx.testScanWindow(
            BoxFit.cover,
            const Rect.fromLTRB(
              0.25,
              0.38888888888888895,
              0.75,
              0.6111111111111112,
            ),
          );
        });

        test('with BoxFit.contain', () {
          ctx.testScanWindow(
            BoxFit.contain,
            const Rect.fromLTRB(0, 0.25, 1, 0.75),
          );
        });

        test('with BoxFit.scaleDown', () {
          ctx.testScanWindow(
            BoxFit.scaleDown,
            const Rect.fromLTRB(0, 0.25, 1, 0.75),
          );
        });
      },
    );

    group(
      'can compute scan window for landscape widget inside landscape texture',
      () {
        const textureSize = Size(640, 480);
        const widgetSize = Size(320, 120);
        final ctx = ScanWindowTestContext(
          textureSize: textureSize,
          widgetSize: widgetSize,
          scanWindow: Rect.fromLTWH(
            widgetSize.width / 4,
            widgetSize.height / 4,
            widgetSize.width / 2,
            widgetSize.height / 2,
          ),
        );

        test('with BoxFit.none', () {
          ctx.testScanWindow(
            BoxFit.none,
            const Rect.fromLTRB(0.375, 0.4375, 0.625, 0.5625),
          );
        });

        test('with BoxFit.fill', () {
          ctx.testScanWindow(
            BoxFit.fill,
            const Rect.fromLTRB(0.25, 0.25, 0.75, 0.75),
          );
        });

        test('with BoxFit.fitHeight', () {
          ctx.testScanWindow(
            BoxFit.fitHeight,
            const Rect.fromLTRB(0, 0.25, 1, 0.75),
          );
        });

        test('with BoxFit.fitWidth', () {
          ctx.testScanWindow(
            BoxFit.fitWidth,
            const Rect.fromLTRB(0.25, 0.375, 0.75, 0.625),
          );
        });

        test('with BoxFit.cover', () {
          ctx.testScanWindow(
            BoxFit.cover,
            const Rect.fromLTRB(0.25, 0.375, 0.75, 0.625),
          );
        });

        test('with BoxFit.contain', () {
          ctx.testScanWindow(
            BoxFit.contain,
            const Rect.fromLTRB(0, 0.25, 1, 0.75),
          );
        });

        test('with BoxFit.scaleDown', () {
          ctx.testScanWindow(
            BoxFit.scaleDown,
            const Rect.fromLTRB(0, 0.25, 1, 0.75),
          );
        });
      },
    );
  });
}

class ScanWindowTestContext {
  ScanWindowTestContext({
    required this.textureSize,
    required this.widgetSize,
    required this.scanWindow,
  });

  final Size textureSize;
  final Size widgetSize;
  final Rect scanWindow;

  void testScanWindow(BoxFit fit, Rect expected) {
    final actual =
        ScanWindowUtils.calculateScanWindowRelativeToTextureInPercentage(
          fit,
          scanWindow,
          textureSize: textureSize,
          widgetSize: widgetSize,
        );

    // Use closeTo because of possible floating point errors.
    expect(actual.left, closeTo(expected.left, 0.0001));
    expect(actual.top, closeTo(expected.top, 0.0001));
    expect(actual.right, closeTo(expected.right, 0.0001));
    expect(actual.bottom, closeTo(expected.bottom, 0.0001));
  }
}
