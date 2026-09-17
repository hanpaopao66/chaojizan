package com.chaojizan.user

import android.content.Intent
import android.net.Uri
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.UUID

/**
 * 系统分享面板收进来的入口(ACTION_SEND / ACTION_SEND_MULTIPLE)。
 *
 * 系统面板只列**声明过接收分享**的 App,声明在 AndroidManifest 里;
 * 这里负责把 intent 里的文字/图片取出来交给 Flutter。
 *
 * 图片先拷进 cacheDir:分享方给的是 content:// URI,读取授权只在这个
 * intent 还活着的时候有效,Flutter 侧晚一步去读就可能 SecurityException。
 * 冷启动的内容存着等 Flutter 来取(takeInitialShare),热启动直接推(onShare)。
 */
class MainActivity : FlutterActivity() {
    private var channel: MethodChannel? = null
    private var pending: Map<String, Any?>? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
        channel?.setMethodCallHandler { call, result ->
            when (call.method) {
                "takeInitialShare" -> {
                    val share = pending
                    pending = null
                    // 取过之后把 intent 换掉:进程被杀后重启时,同一份分享不会再发一次
                    if (share != null) setIntent(Intent(Intent.ACTION_MAIN))
                    result.success(share)
                }
                else -> result.notImplemented()
            }
        }
        // 冷启动:拉起 App 的就是一个分享
        pending = parseShare(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val share = parseShare(intent) ?: return
        val c = channel
        if (c != null) c.invokeMethod("onShare", share) else pending = share
    }

    private fun parseShare(intent: Intent?): Map<String, Any?>? {
        if (intent == null) return null
        return when (intent.action) {
            Intent.ACTION_SEND -> {
                @Suppress("DEPRECATION")
                val uri = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
                val files = uri?.let { listOfNotNull(copyToCache(it)) } ?: emptyList()
                shareMap(intent.getStringExtra(Intent.EXTRA_TEXT), files)
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                @Suppress("DEPRECATION")
                val uris = intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
                val files = uris?.mapNotNull { copyToCache(it) } ?: emptyList()
                shareMap(intent.getStringExtra(Intent.EXTRA_TEXT), files)
            }
            else -> null
        }
    }

    private fun shareMap(text: String?, files: List<String>): Map<String, Any?>? {
        if (text.isNullOrBlank() && files.isEmpty()) return null
        return mapOf("text" to text, "files" to files)
    }

    /** content:// → 应用 cache 里的真实文件。读不出来返回 null,不挡其他内容。 */
    private fun copyToCache(uri: Uri): String? {
        return try {
            val ext = when (contentResolver.getType(uri)) {
                "image/png" -> ".png"
                "image/webp" -> ".webp"
                "image/gif" -> ".gif"
                "image/heic", "image/heif" -> ".heic"
                else -> ".jpg"
            }
            val dir = File(cacheDir, "shared").apply { mkdirs() }
            val out = File(dir, UUID.randomUUID().toString() + ext)
            contentResolver.openInputStream(uri)?.use { input ->
                out.outputStream().use { input.copyTo(it) }
            } ?: return null
            out.absolutePath
        } catch (e: Exception) {
            null
        }
    }

    companion object {
        private const val CHANNEL = "com.chaojizan.user/share"
    }
}
