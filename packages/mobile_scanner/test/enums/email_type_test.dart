import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/src/enums/email_type.dart';

void main() {
  group('EmailType tests', () {
    test('can be created from raw value', () {
      const values = <int, EmailType>{
        0: EmailType.unknown,
        1: EmailType.work,
        2: EmailType.home,
      };

      for (final entry in values.entries) {
        final result = EmailType.fromRawValue(entry.key);

        expect(result, entry.value);
      }
    });

    test('invalid raw value returns EmailType.unknown', () {
      const negative = -1;
      const outOfRange = 3;

      expect(EmailType.fromRawValue(negative), EmailType.unknown);
      expect(EmailType.fromRawValue(outOfRange), EmailType.unknown);
    });

    test('can be converted to raw value', () {
      const values = <EmailType, int>{
        EmailType.unknown: 0,
        EmailType.work: 1,
        EmailType.home: 2,
      };

      for (final entry in values.entries) {
        final result = entry.key.rawValue;

        expect(result, entry.value);
      }
    });
  });
}
