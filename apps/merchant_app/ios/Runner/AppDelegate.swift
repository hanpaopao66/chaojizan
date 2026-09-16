import Flutter
import UIKit
import UserNotifications

/// 苹果推送(APNs)直连 —— 不接任何第三方 SDK(#384)。
///
/// 系统把 device token 交给 `didRegisterForRemoteNotifications…`,我们原样转成十六进制
/// 发给 Dart,Dart 再报给自己的服务端(`POST /push/v1/devices`)。中间没有别人。
///
/// 三件容易错的事:
///  1. **要先拿到授权再注册**。没授权也能拿到 token,但通知不会弹 —— 看着像"推送坏了";
///  2. token 会变(重装、恢复备份、换机),所以每次启动都注册一次、每次都把新的报上去;
///  3. 沙箱和生产是两台服务器:Xcode / TestFlight 装的包拿到的是沙箱 token。
///     这里按编译配置如实告诉 Dart,由服务端选发到哪台 —— 猜错就是静默收不到。
@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var channel: FlutterMethodChannel?

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    UNUserNotificationCenter.current().delegate = self
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    guard let messenger = engineBridge.applicationEngine?.binaryMessenger else { return }
    let ch = FlutterMethodChannel(name: "superz/push", binaryMessenger: messenger)
    channel = ch
    ch.setMethodCallHandler { [weak self] call, result in
      switch call.method {
      case "register":
        // 先问授权,再注册。用户拒了就直接告诉 Dart,别让它干等一个永远不来的 token
        UNUserNotificationCenter.current().requestAuthorization(
          options: [.alert, .sound, .badge]
        ) { granted, _ in
          DispatchQueue.main.async {
            guard granted else {
              result(FlutterError(code: "denied", message: "用户没同意通知", details: nil))
              return
            }
            UIApplication.shared.registerForRemoteNotifications()
            result(nil)  // token 稍后由 onToken 送过来
          }
        }
      case "sandbox":
        result(self?.isSandbox() ?? false)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  override func application(
    _ application: UIApplication,
    didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
  ) {
    let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
    channel?.invokeMethod("onToken", arguments: ["token": hex, "sandbox": isSandbox()])
    super.application(application, didRegisterForRemoteNotificationsWithDeviceToken: deviceToken)
  }

  override func application(
    _ application: UIApplication,
    didFailToRegisterForRemoteNotificationsWithError error: Error
  ) {
    // 模拟器、没配推送能力的包会走到这儿。**不崩、不弹** —— 主通道(长连接)照常工作
    channel?.invokeMethod("onError", arguments: ["message": error.localizedDescription])
    super.application(application, didFailToRegisterForRemoteNotificationsWithError: error)
  }

  /// 这个包是不是发到沙箱那台服务器。
  ///
  /// 判据是打包时嵌的 `aps-environment`(Xcode / TestFlight 是 development,
  /// App Store 是 production)—— 不用 `#if DEBUG`:TestFlight 是 release 编的,
  /// 但拿的是沙箱 token,只看编译模式会判反。
  private func isSandbox() -> Bool {
    guard let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
          let data = try? Data(contentsOf: url),
          let text = String(data: data, encoding: .isoLatin1)
    else {
      // 拿不到描述文件(App Store 包里没有这个文件)= 生产
      return false
    }
    return text.contains("<key>aps-environment</key>")
      && text.range(of: "<key>aps-environment</key>\\s*<string>development</string>",
                    options: .regularExpression) != nil
  }
}
