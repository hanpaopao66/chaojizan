import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/src/enums/detection_speed.dart';

void main() {
  group('DetectionSpeed tests', () {
    test('can be created from raw value', () {
      const values = <int, DetectionSpeed>{
        0: DetectionSpeed.noDuplicates,
        1: DetectionSpeed.normal,
        2: DetectionSpeed.unrestricted,
      };

      for (final entry in values.entries) {
        final result = DetectionSpeed.fromRawValue(entry.key);

        expect(result, entry.value);
      }
    });

    test('invalid raw value throws argument error', () {
      const negative = -1;
      const outOfRange = 3;

      expect(() => DetectionSpeed.fromRawValue(negative), throwsArgumentError);
      expect(
        () => DetectionSpeed.fromRawValue(outOfRange),
        throwsArgumentError,
      );
    });

    test('can be converted to raw value', () {
      const values = <DetectionSpeed, int>{
        DetectionSpeed.noDuplicates: 0,
        DetectionSpeed.normal: 1,
        DetectionSpeed.unrestricted: 2,
      };

      for (final entry in values.entries) {
        final result = entry.key.rawValue;

        expect(result, entry.value);
      }
    });
  });
}
