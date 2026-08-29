pluginManagement {
    val flutterSdkPath =
        run {
            val properties = java.util.Properties()
            file("local.properties").inputStream().use { properties.load(it) }
            val flutterSdkPath = properties.getProperty("flutter.sdk")
            require(flutterSdkPath != null) { "flutter.sdk not set in local.properties" }
            flutterSdkPath
        }

    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")

    repositories {
        // 国内镜像只在**国内网络**上是加速,在海外 runner 上是瓶颈。
        // Gradle 对 5xx/网络错误是 fail fast —— 只有 404 才往下找下一个仓库,
        // 所以「阿里云在前、google() 在后」这条 fallback 链根本兜不住:
        // 镜像一抖,整个解析直接失败(2026-08-29 发 v0.14.3 时就是这样挂的)。
        //
        // ⚠️ 这个开关 build.gradle.kts 里早就加过了,**唯独漏了这里** ——
        // 而 pluginManagement 比 build.gradle.kts 更早执行,
        // 所以漏在这里等于整条防线没生效。
        //
        // CI 里设 SUPERZ_SKIP_CN_MIRROR=1 直连官方源(runner 在海外,
        // dl.google.com 是通的);开发机不设,照旧走镜像 ——
        // 那边的问题正相反,是 dl.google.com 被挡。
        if (System.getenv("SUPERZ_SKIP_CN_MIRROR") != "1") {
            maven { url = uri("https://maven.aliyun.com/repository/google") }
            maven { url = uri("https://maven.aliyun.com/repository/public") }
            maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        }
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "9.0.1" apply false
    id("org.jetbrains.kotlin.android") version "2.3.20" apply false
}

include(":app")
