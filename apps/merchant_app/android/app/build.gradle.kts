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

// 分发渠道(#192):store = 应用商店包,不传(self)= 官网直链包。
// 传法:flutter build apk --release -PSUPERZ_CHANNEL=store
//       (Dart 侧还要 --dart-define=SUPERZ_CHANNEL=store 把更新检查一起关掉,
//        见 shared/update_checker.dart;两边都传才算一个完整的商店包)
// 国内商店明令禁止绕过审核的应用内自更新,所以 store 包的清单里
// 不能有 apk_installer 带进来的 REQUEST_INSTALL_PACKAGES(src/store/AndroidManifest.xml 摘掉它)
val storeChannel = ((project.findProperty("SUPERZ_CHANNEL") as String?)
    ?: System.getenv("SUPERZ_CHANNEL")) == "store"
if (storeChannel) {
    logger.lifecycle("== 渠道 store:release 清单将移除 REQUEST_INSTALL_PACKAGES ==")
}

android {
    namespace = "com.chaojizan.merchant"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        // 只挂在 release 上:商店包必然是 release 构建;debug 的清单另有正事
        // (放行本地明文,见 src/debug/AndroidManifest.xml),不能被顶掉
        if (storeChannel) {
            getByName("release").manifest.srcFile("src/store/AndroidManifest.xml")
        }
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.chaojizan.merchant"
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
