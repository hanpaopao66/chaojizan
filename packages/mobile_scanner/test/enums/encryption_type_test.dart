import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/src/enums/encryption_type.dart';

void main() {
  group('EncryptionType tests', () {
    test('can be created from raw value', () {
      const values = <int, EncryptionType>{
        0: EncryptionType.unknown,
        1: EncryptionType.open,
        2: EncryptionType.wpa,
        3: EncryptionType.wep,
      };

      for (final entry in values.entries) {
        final result = EncryptionType.fromRawValue(entry.key);

        expect(result, entry.value);
      }
    });

    test('invalid raw value returns EncryptionType.unknown', () {
      const negative = -1;
      const outOfRange = 4;

      expect(EncryptionType.fromRawValue(negative), EncryptionType.unknown);
      expect(EncryptionType.fromRawValue(outOfRange), EncryptionType.unknown);
    });

    test('can be converted to raw value', () {
      const values = <EncryptionType, int>{
        EncryptionType.unknown: 0,
        EncryptionType.open: 1,
        EncryptionType.wpa: 2,
        EncryptionType.wep: 3,
      };

      for (final entry in values.entries) {
        final result = entry.key.rawValue;

        expect(result, entry.value);
      }
    });
  });
}
