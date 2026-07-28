import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val keystoreProperties = Properties().apply {
    val f = rootProject.file("key.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.chaojizan.user"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.chaojizan.user"
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

    signingConfigs {
        // 正式签名读 android/key.properties(不入库);没有该文件时不创建,
        // release 回落 debug 签名,保证任意机器 flutter run --release 可用
        if (keystoreProperties.isNotEmpty()) {
            create("release") {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            // 应用商店/备案用正式签名;签名变更后旧的调试签名包需卸载重装
            signingConfig = if (keystoreProperties.isNotEmpty())
                signingConfigs.getByName("release")
            else signingConfigs.getByName("debug")
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
