allprojects {
    repositories {
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
