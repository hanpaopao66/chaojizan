import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/src/enums/phone_type.dart';

void main() {
  group('PhoneType tests', () {
    test('can be created from raw value', () {
      const values = <int, PhoneType>{
        0: PhoneType.unknown,
        1: PhoneType.work,
        2: PhoneType.home,
        3: PhoneType.fax,
        4: PhoneType.mobile,
      };

      for (final entry in values.entries) {
        final result = PhoneType.fromRawValue(entry.key);

        expect(result, entry.value);
      }
    });

    test('invalid raw value returns PhoneType.unknown', () {
      const negative = -1;
      const outOfRange = 5;

      expect(PhoneType.fromRawValue(negative), PhoneType.unknown);
      expect(PhoneType.fromRawValue(outOfRange), PhoneType.unknown);
    });

    test('can be converted to raw value', () {
      const values = <PhoneType, int>{
        PhoneType.unknown: 0,
        PhoneType.work: 1,
        PhoneType.home: 2,
        PhoneType.fax: 3,
        PhoneType.mobile: 4,
      };

      for (final entry in values.entries) {
        final result = entry.key.rawValue;

        expect(result, entry.value);
      }
    });
  });
}
