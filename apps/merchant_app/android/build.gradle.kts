allprojects {
    // buildscript 的仓库要单独配一份:上面 allprojects.repositories 只管
    // 依赖解析,管不到子项目**构建脚本自己的类路径**。
    // 而 Flutter 插件(audioplayers_android、print_bluetooth_thermal 等)
    // 在自己的 build.gradle 里写死了 google(),那是 pub 缓存里的第三方代码,
    // 改不了也不该改 —— 只能在这里把镜像喂给它们
    buildscript {
        repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/public") }
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
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/public") }
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
// flutter_tencent_map 1.0.1 自己声明 compileSdkVersion 31,而它的传递依赖
// (flutter_plugin_android_lifecycle)要求编译到 36 —— 开箱构建直接失败:
//   Execution failed for task ':flutter_tencent_map:checkDebugAarMetadata'
// 这里把所有插件模块强行抬到 36。
//
// **必须放在下面的 evaluationDependsOn 之前**:那句会立刻求值子工程,
// 之后再挂 afterEvaluate 会报 "already evaluated"(踩过)。
subprojects {
    afterEvaluate {
        extensions.findByName("android")?.let { ext ->
            ext.javaClass.methods.firstOrNull {
                it.name == "setCompileSdkVersion" &&
                    it.parameterTypes.size == 1 &&
                    it.parameterTypes[0] == Int::class.javaPrimitiveType
            }?.invoke(ext, 36)
        }
    }
}

subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
