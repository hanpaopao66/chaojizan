package com.chaojizan.apk_installer

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * 自建分发渠道的安装器(#123)。
 *
 * 只做两件事:判断/引导「安装未知应用」授权,以及把下载好的 APK 交给系统安装器。
 * 下载和 SHA-256 校验都在 Dart 侧做 —— 原生面越小,三端一起出问题的风险越小。
 */
class ApkInstallerPlugin : FlutterPlugin, ActivityAware, MethodChannel.MethodCallHandler {

    private lateinit var channel: MethodChannel
    private lateinit var context: Context
    private var activity: Activity? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        channel = MethodChannel(binding.binaryMessenger, "superz/apk_installer")
        channel.setMethodCallHandler(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel.setMethodCallHandler(null)
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivity() {
        activity = null
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        activity = binding.activity
    }

    override fun onDetachedFromActivityForConfigChanges() {
        activity = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            // Android 8.0 起「安装未知应用」是按应用授权的,装不装得上先问这个
            "canInstall" -> result.success(
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) true
                else context.packageManager.canRequestPackageInstalls()
            )

            // 跳到本应用的「安装未知应用」设置页(不是全局设置页,少让用户找一层)
            "openInstallSettings" -> {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
                    result.success(false)
                    return
                }
                val target = activity ?: context
                val intent = Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:${context.packageName}")
                )
                if (target !is Activity) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                try {
                    target.startActivity(intent)
                    result.success(true)
                } catch (e: Exception) {
                    // 个别定制 ROM 没有这个页面;调用方会退回浏览器下载
                    result.success(false)
                }
            }

            "install" -> {
                val path = call.argument<String>("path")
                if (path.isNullOrEmpty()) {
                    result.error("bad_args", "缺少安装包路径", null)
                    return
                }
                val file = File(path)
                if (!file.exists()) {
                    result.error("not_found", "安装包不存在或已被清理", null)
                    return
                }
                try {
                    val uri: Uri = FileProvider.getUriForFile(
                        context, "${context.packageName}.apkprovider", file
                    )
                    val intent = Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(uri, "application/vnd.android.package-archive")
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    (activity ?: context).startActivity(intent)
                    result.success(true)
                } catch (e: Exception) {
                    result.error("install_failed", e.message ?: "拉起安装器失败", null)
                }
            }

            else -> result.notImplemented()
        }
    }
}
