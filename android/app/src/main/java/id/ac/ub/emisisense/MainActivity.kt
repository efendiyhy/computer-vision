package id.ac.ub.emisisense

import android.Manifest
import android.app.DownloadManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.util.Base64
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.*
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

/** Membungkus dashboard web agar terasa seperti aplikasi asli. */
class MainActivity : AppCompatActivity() {
    private lateinit var store: Store
    private lateinit var web: WebView
    private lateinit var swipe: SwipeRefreshLayout
    private lateinit var progress: ProgressBar
    private lateinit var errorView: View
    private lateinit var errorMsg: TextView
    private lateinit var root: FrameLayout
    private var refreshLocked = false
    private var failed = false
    private var customView: View? = null
    private var customCallback: WebChromeClient.CustomViewCallback? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    private val chooser = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val data = WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data)
        fileCallback?.onReceiveValue(data)
        fileCallback = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        if (store.url.isEmpty()) { changeServerNow(); return }
        setContentView(R.layout.activity_main)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        root = findViewById(R.id.root)
        web = findViewById(R.id.web)
        swipe = findViewById(R.id.swipe)
        progress = findViewById(R.id.progress)
        errorView = findViewById(R.id.errorView)
        errorMsg = findViewById(R.id.errorMsg)
        findViewById<Button>(R.id.retry).setOnClickListener { load() }
        findViewById<Button>(R.id.change).setOnClickListener { changeServerNow() }

        swipe.setColorSchemeColors(Color.parseColor("#1550D8"))
        swipe.setOnRefreshListener { failed = false; web.reload() }
        swipe.setOnChildScrollUpCallback { _, _ -> refreshLocked || web.scrollY > 0 }

        setupWebView()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when {
                    customView != null -> hideCustomView()
                    web.canGoBack() -> web.goBack()
                    else -> finish()
                }
            }
        })
        if (savedInstanceState != null) web.restoreState(savedInstanceState) else load()
    }

    private fun load() {
        failed = false
        errorView.visibility = View.GONE
        web.loadUrl(store.url + "/")
    }

    private fun changeServerNow() {
        startActivity(Intent(this, ConnectActivity::class.java).putExtra("stay", true))
        finish()
    }

    @Suppress("SetJavaScriptEnabled")
    private fun setupWebView() {
        val s = web.settings
        s.javaScriptEnabled = true
        s.domStorageEnabled = true
        s.mediaPlaybackRequiresUserGesture = false
        s.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        s.setSupportZoom(false)
        s.builtInZoomControls = false
        s.userAgentString = s.userAgentString + " EmisiSenseApp/" + BuildConfig.VERSION_NAME
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.setBackgroundColor(Color.TRANSPARENT)
        web.addJavascriptInterface(Bridge(), "EmisiApp")

        web.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                progress.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String?) {
                progress.visibility = View.GONE
                swipe.isRefreshing = false
                if (!failed) errorView.visibility = View.GONE
            }

            override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
                if (req.isForMainFrame) {
                    failed = true
                    errorMsg.text = err.description?.toString() ?: ""
                    errorView.visibility = View.VISIBLE
                    swipe.isRefreshing = false
                }
            }

            override fun onReceivedHttpAuthRequest(view: WebView, h: HttpAuthHandler, host: String?, realm: String?) {
                val saved = store.password
                if (saved.isNotEmpty() && !h.useHttpAuthUsernamePassword()) {
                    h.proceed("", saved); return
                }
                askPassword(h)
            }

            override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                val u = req.url
                val base = Uri.parse(store.url)
                if (u.host == base.host && u.port == base.port) return false
                // Tautan luar (mis. ek-instrumentation.com) dibuka di peramban.
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, u)) }
                return true
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, p: Int) {
                progress.progress = p
            }

            override fun onShowFileChooser(w: WebView, cb: ValueCallback<Array<Uri>>, p: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = cb
                return try {
                    chooser.launch(p.createIntent()); true
                } catch (e: Exception) {
                    fileCallback = null; false
                }
            }

            override fun onShowCustomView(view: View, cb: CustomViewCallback) {
                if (customView != null) { cb.onCustomViewHidden(); return }
                customView = view
                customCallback = cb
                root.addView(view, FrameLayout.LayoutParams(-1, -1))
                setSystemBarsVisible(false)
            }

            override fun onHideCustomView() = hideCustomView()
        }

        web.setDownloadListener { url, ua, disp, mime, _ -> download(url, ua, disp, mime) }
    }

    private fun hideCustomView() {
        customView?.let { root.removeView(it) }
        customView = null
        customCallback?.onCustomViewHidden()
        customCallback = null
        setSystemBarsVisible(true)
    }

    private fun setSystemBarsVisible(show: Boolean) {
        val c = WindowInsetsControllerCompat(window, window.decorView)
        if (show) c.show(WindowInsetsCompat.Type.systemBars()) else {
            c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            c.hide(WindowInsetsCompat.Type.systemBars())
        }
    }

    private fun askPassword(h: HttpAuthHandler) {
        val input = EditText(this).apply {
            hint = getString(R.string.hint_password)
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val box = LinearLayout(this).apply {
            setPadding(60, 20, 60, 0); addView(input, LinearLayout.LayoutParams(-1, -2))
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.auth_title)
            .setView(box)
            .setPositiveButton(R.string.ok) { _, _ ->
                val pw = input.text.toString()
                store.password = pw
                h.proceed("", pw)
            }
            .setNegativeButton(R.string.cancel) { _, _ -> h.cancel() }
            .setOnCancelListener { h.cancel() }
            .show()
    }

    private fun download(url: String, ua: String?, disp: String?, mime: String?) {
        if (Build.VERSION.SDK_INT < 29 &&
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), 1)
            Toast.makeText(this, "Izinkan penyimpanan, lalu ulangi unduhan.", Toast.LENGTH_LONG).show()
            return
        }
        try {
            val name = URLUtil.guessFileName(url, disp, mime)
            val req = DownloadManager.Request(Uri.parse(url))
                .setTitle(name)
                .setMimeType(mime)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
            if (ua != null) req.addRequestHeader("User-Agent", ua)
            CookieManager.getInstance().getCookie(url)?.let { req.addRequestHeader("Cookie", it) }
            if (store.password.isNotEmpty()) {
                val tok = Base64.encodeToString(":${store.password}".toByteArray(), Base64.NO_WRAP)
                req.addRequestHeader("Authorization", "Basic $tok")
            }
            (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
            Toast.makeText(this, R.string.downloading, Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "Unduhan gagal: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    /** Dipanggil dari web lewat window.EmisiApp. */
    inner class Bridge {
        @JavascriptInterface
        fun setBars(top: String, bottom: String, dark: Boolean) {
            runOnUiThread {
                runCatching {
                    val t = Color.parseColor(top)
                    val b = Color.parseColor(bottom)
                    window.statusBarColor = t
                    window.navigationBarColor = b
                    root.setBackgroundColor(t)
                    val c = WindowInsetsControllerCompat(window, window.decorView)
                    c.isAppearanceLightStatusBars = !dark
                    c.isAppearanceLightNavigationBars = false
                }
            }
        }

        @JavascriptInterface
        fun lockRefresh(lock: Boolean) { refreshLocked = lock }

        @JavascriptInterface
        fun tick() {
            runOnUiThread { web.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP) }
        }

        @JavascriptInterface
        fun changeServer() { runOnUiThread { changeServerNow() } }

        @JavascriptInterface
        fun server(): String = store.url

        @JavascriptInterface
        fun version(): String = BuildConfig.VERSION_NAME
    }

    override fun onSaveInstanceState(out: Bundle) {
        super.onSaveInstanceState(out)
        if (::web.isInitialized) web.saveState(out)
    }

    override fun onResume() { super.onResume(); if (::web.isInitialized) web.onResume() }
    override fun onPause() { if (::web.isInitialized) web.onPause(); super.onPause() }
    override fun onDestroy() {
        if (::web.isInitialized) { (web.parent as? ViewGroup)?.removeView(web); web.destroy() }
        super.onDestroy()
    }
}
