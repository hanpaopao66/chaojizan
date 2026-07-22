plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.chaojizan.rider"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.chaojizan.rider"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // 极光推送:拿到 AppKey 后在 gradle.properties 或环境变量里配 JPUSH_APPKEY
        // (Dart 侧还需 --dart-define=SUPERZ_JPUSH_KEY=同一个值,见 shared/push_service.dart)
        manifestPlaceholders["JPUSH_APPKEY"] = (project.findProperty("JPUSH_APPKEY") as String?) ?: ""
        manifestPlaceholders["JPUSH_CHANNEL"] = "developer"
        // 发版脚本不用 --split-per-abi(避免 versionCode ABI 偏移),这里过滤掉
        // 第三方插件带的非 arm64 .so,否则会全部打进单 APK 白白涨体积
        ndk { abiFilters += "arm64-v8a" }
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
