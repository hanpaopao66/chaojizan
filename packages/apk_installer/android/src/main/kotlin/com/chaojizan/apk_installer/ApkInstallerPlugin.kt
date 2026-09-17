package com.chaojizan.apk_installer

import android.app.Activity
import android.app.DownloadManager
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
 * 原来只做两件事:判断/引导「安装未知应用」授权,以及把下载好的 APK 交给系统安装器,
 * 下载和校验都在 Dart 侧 —— 原生面越小,三端一起出问题的风险越小。
 *
 * **后台下载这一条只能落在原生**(2026-09-17 加):Dart 侧那份下载活在 Flutter
 * 引擎里,App 被系统回收就断了,而且没法在通知栏显示进度。系统的 [DownloadManager]
 * 正是干这个的 —— 退到后台、熄屏、甚至进程被杀都继续下,进度由系统自己画在通知栏
 * (**那是系统的通知,不占我们的通知权限** —— 三端清单是为上架特意精简过的,
 * 不该为这个功能新增一条权限)。
 *
 * **SHA-256 校验仍然留在 Dart 侧**,而且刻意关掉了 DownloadManager 的「下载完成」
 * 通知([DownloadManager.Request.VISIBILITY_VISIBLE]):那条通知点一下就装,
 * 会绕过校验 —— 装一个没校验过的 APK,比多点两下严重得多。
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

            // ---- 后台下载:交给系统的 DownloadManager ----
            //
            // 落点用 setDestinationInExternalFilesDir + "apk/",和 FileProvider 那份
            // superz_apk_paths.xml 声明的路径**是同一个目录** —— 下完就地能装,
            // 不用再挪一次(挪一次就多一次失败的机会,而且要额外的存储权限)
            "download" -> {
                val url = call.argument<String>("url")
                val name = call.argument<String>("fileName")
                if (url.isNullOrEmpty() || name.isNullOrEmpty()) {
                    result.error("bad_args", "缺少下载地址或文件名", null)
                    return
                }
                try {
                    val dm = context.getSystemService(Context.DOWNLOAD_SERVICE)
                            as DownloadManager
                    val req = DownloadManager.Request(Uri.parse(url)).apply {
                        setTitle(call.argument<String>("title") ?: "正在下载新版本")
                        setMimeType("application/vnd.android.package-archive")
                        // **只显示进度,不显示「下载完成」那条。**
                        // 那条点一下就直接装,会绕过 Dart 侧的 SHA-256 校验
                        setNotificationVisibility(
                            DownloadManager.Request.VISIBILITY_VISIBLE)
                        setDestinationInExternalFilesDir(context, null, "apk/$name")
                        setAllowedOverRoaming(false)
                    }
                    result.success(dm.enqueue(req))
                } catch (e: Exception) {
                    result.error("download_failed", e.message ?: "排不进下载队列", null)
                }
            }

            // 进度与结果。**回的是数字状态,不替调用方下判断** ——
            // "下完了但校验不过"这类事由 Dart 侧决定怎么办
            "downloadStatus" -> {
                val id = (call.argument<Number>("id"))?.toLong()
                if (id == null) {
                    result.error("bad_args", "缺少下载编号", null)
                    return
                }
                try {
                    val dm = context.getSystemService(Context.DOWNLOAD_SERVICE)
                            as DownloadManager
                    dm.query(DownloadManager.Query().setFilterById(id)).use { c ->
                        if (c == null || !c.moveToFirst()) {
                            // 被用户在通知栏划掉、或者系统清理了记录
                            result.success(mapOf("status" to "gone"))
                            return
                        }
                        fun col(n: String) = c.getColumnIndexOrThrow(n)
                        val st = c.getInt(col(DownloadManager.COLUMN_STATUS))
                        val soFar = c.getLong(
                            col(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
                        val total = c.getLong(
                            col(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
                        val uri = c.getString(col(DownloadManager.COLUMN_LOCAL_URI))
                        result.success(mapOf(
                            "status" to when (st) {
                                DownloadManager.STATUS_SUCCESSFUL -> "done"
                                DownloadManager.STATUS_FAILED -> "failed"
                                DownloadManager.STATUS_PAUSED -> "paused"
                                else -> "running"
                            },
                            "soFar" to soFar,
                            "total" to total,
                            "path" to uri?.let { Uri.parse(it).path },
                            "reason" to c.getInt(col(DownloadManager.COLUMN_REASON))))
                    }
                } catch (e: Exception) {
                    result.error("query_failed", e.message ?: "查不到这条下载", null)
                }
            }

            "cancelDownload" -> {
                val id = (call.argument<Number>("id"))?.toLong()
                if (id != null) {
                    try {
                        (context.getSystemService(Context.DOWNLOAD_SERVICE)
                                as DownloadManager).remove(id)
                    } catch (_: Exception) {}
                }
                result.success(true)
            }

            else -> result.notImplemented()
        }
    }
}
