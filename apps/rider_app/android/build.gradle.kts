allprojects {
    // buildscript 的仓库要单独配一份:上面 allprojects.repositories 只管
    // 依赖解析,管不到子项目**构建脚本自己的类路径**。
    // 而 Flutter 插件(audioplayers_android、print_bluetooth_thermal 等)
    // 在自己的 build.gradle 里写死了 google(),那是 pub 缓存里的第三方代码,
    // 改不了也不该改 —— 只能在这里把镜像喂给它们
    buildscript {
        repositories {
        // 国内镜像只在**国内网络**上是加速,在海外 runner 上是瓶颈:
        // 2026-08-23 发 v0.13.0 时 aliyun 的 google 镜像 502,三端全挂。
        // 而 Gradle 对 5xx 是 fail fast —— 只有 404 才往下找下一个仓库,
        // 所以「阿里云在前、google() 在后」这条 fallback 链根本没兜住。
        //
        // CI 里设 SUPERZ_SKIP_CN_MIRROR=1 跳过镜像直连官方源(runner 在海外,
        // dl.google.com 是通的);开发机不设,照旧走镜像 ——
        // 那边的问题正相反,是 dl.google.com 被挡。
        if (System.getenv("SUPERZ_SKIP_CN_MIRROR") != "1") {
            maven { url = uri("https://maven.aliyun.com/repository/google") }
            maven { url = uri("https://maven.aliyun.com/repository/public") }
        }
        google()
        mavenCentral()
        }
    }
}

allprojects {
    repositories {
        // 国内镜像放前面,官方源保留兜底。
        // dl.google.com 在很多国内网络下直接不通(实测 12s 超时),
        // 只写 google() 的话换个网络就打不出包 —— 而"打不出包"这件事
        // 只会在发版当天才发现。阿里云的 google 镜像是完整代理,
        // 拉不到的再回落官方源
        // 国内镜像只在**国内网络**上是加速,在海外 runner 上是瓶颈:
        // 2026-08-23 发 v0.13.0 时 aliyun 的 google 镜像 502,三端全挂。
        // 而 Gradle 对 5xx 是 fail fast —— 只有 404 才往下找下一个仓库,
        // 所以「阿里云在前、google() 在后」这条 fallback 链根本没兜住。
        //
        // CI 里设 SUPERZ_SKIP_CN_MIRROR=1 跳过镜像直连官方源(runner 在海外,
        // dl.google.com 是通的);开发机不设,照旧走镜像 ——
        // 那边的问题正相反,是 dl.google.com 被挡。
        if (System.getenv("SUPERZ_SKIP_CN_MIRROR") != "1") {
            maven { url = uri("https://maven.aliyun.com/repository/google") }
            maven { url = uri("https://maven.aliyun.com/repository/public") }
        }
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
// amap_map 等旧插件钉在 compileSdk 35,而新版 lifecycle 插件要求 36:
// 在任何子项目求值前注册 afterEvaluate,评估结束后统一改写(必须放在 evaluationDependsOn 之前)
subprojects {
    afterEvaluate {
        extensions.findByType(com.android.build.gradle.BaseExtension::class.java)
            ?.compileSdkVersion(36)
    }
}

subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
