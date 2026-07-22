import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/src/enums/camera_facing.dart';
import 'package:mobile_scanner/src/enums/camera_lens_type.dart';
import 'package:mobile_scanner/src/objects/switch_camera_option.dart';

void main() {
  group('SwitchCameraOption tests', () {
    group('ToggleDirection', () {
      test('can be created with const constructor', () {
        const option = ToggleDirection();

        expect(option, isA<SwitchCameraOption>());
        expect(option, isA<ToggleDirection>());
      });

      test('two instances are equal', () {
        const option1 = ToggleDirection();
        const option2 = ToggleDirection();

        expect(option1, equals(option2));
      });
    });

    group('ToggleLensType', () {
      test('can be created with const constructor', () {
        const option = ToggleLensType();

        expect(option, isA<SwitchCameraOption>());
        expect(option, isA<ToggleLensType>());
      });

      test('two instances are equal', () {
        const option1 = ToggleLensType();
        const option2 = ToggleLensType();

        expect(option1, equals(option2));
      });
    });

    group('SelectCamera', () {
      test('can be created with default values', () {
        const option = SelectCamera();

        expect(option, isA<SwitchCameraOption>());
        expect(option, isA<SelectCamera>());
        expect(option.facingDirection, isNull);
        expect(option.lensType, CameraLensType.any);
      });

      test('can be created with facing direction only', () {
        const option = SelectCamera(facingDirection: CameraFacing.front);

        expect(option.facingDirection, CameraFacing.front);
        expect(option.lensType, CameraLensType.any);
      });

      test('can be created with lens type only', () {
        const option = SelectCamera(lensType: CameraLensType.wide);

        expect(option.facingDirection, isNull);
        expect(option.lensType, CameraLensType.wide);
      });

      test('can be created with both facing direction and lens type', () {
        const option = SelectCamera(
          facingDirection: CameraFacing.back,
          lensType: CameraLensType.zoom,
        );

        expect(option.facingDirection, CameraFacing.back);
        expect(option.lensType, CameraLensType.zoom);
      });

      test('can be created with all CameraFacing values', () {
        for (final facing in CameraFacing.values) {
          final option = SelectCamera(facingDirection: facing);

          expect(option.facingDirection, facing);
        }
      });

      test('can be created with all CameraLensType values', () {
        for (final lens in CameraLensType.values) {
          final option = SelectCamera(lensType: lens);

          expect(option.lensType, lens);
        }
      });
    });

    group('pattern matching', () {
      test('can match ToggleDirection', () {
        const SwitchCameraOption option = ToggleDirection();

        final result = switch (option) {
          ToggleDirection() => 'toggle_direction',
          ToggleLensType() => 'toggle_lens',
          SelectCamera() => 'select',
        };

        expect(result, 'toggle_direction');
      });

      test('can match ToggleLensType', () {
        const SwitchCameraOption option = ToggleLensType();

        final result = switch (option) {
          ToggleDirection() => 'toggle_direction',
          ToggleLensType() => 'toggle_lens',
          SelectCamera() => 'select',
        };

        expect(result, 'toggle_lens');
      });

      test('can match SelectCamera and extract properties', () {
        const SwitchCameraOption option = SelectCamera(
          facingDirection: CameraFacing.front,
          lensType: CameraLensType.wide,
        );

        final result = switch (option) {
          ToggleDirection() => 'toggle_direction',
          ToggleLensType() => 'toggle_lens',
          SelectCamera(:final facingDirection, :final lensType) =>
            '${facingDirection?.name}_${lensType.name}',
        };

        expect(result, 'front_wide');
      });

      test('exhaustive pattern matching covers all cases', () {
        final options = <SwitchCameraOption>[
          const ToggleDirection(),
          const ToggleLensType(),
          const SelectCamera(),
        ];

        for (final option in options) {
          // This should compile without errors due to exhaustive matching.
          final result = switch (option) {
            ToggleDirection() => true,
            ToggleLensType() => true,
            SelectCamera() => true,
          };

          expect(result, isTrue);
        }
      });
    });
  });
}
