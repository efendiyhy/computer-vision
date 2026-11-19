package id.ac.ub.emisisense

import android.content.Intent
import android.os.Bundle
import android.util.Base64
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** Layar pertama: cukup isi IP, lalu langsung masuk. */
class ConnectActivity : AppCompatActivity() {
    private lateinit var store: Store
    private lateinit var address: EditText
    private lateinit var password: EditText
    private lateinit var error: TextView
    private lateinit var button: Button
    private var busy = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        // Server tersimpan: langsung masuk, kecuali pengguna baru memilih "Ganti server".
        if (store.url.isNotEmpty() && !intent.getBooleanExtra("stay", false)) {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
            return
        }
        setContentView(R.layout.activity_connect)
        address = findViewById(R.id.address)
        password = findViewById(R.id.password)
        error = findViewById(R.id.error)
        button = findViewById(R.id.connect)
        address.setText(store.url.removePrefix("http://").removeSuffix(":5000"))
        val go = TextView.OnEditorActionListener { _, id, _ ->
            if (id == EditorInfo.IME_ACTION_GO) { connect(); true } else false
        }
        address.setOnEditorActionListener(go)
        password.setOnEditorActionListener(go)
        button.setOnClickListener { connect() }
    }

    private fun showError(msg: String?) {
        error.text = msg ?: ""
        error.visibility = if (msg == null) android.view.View.GONE else android.view.View.VISIBLE
    }

    private fun connect() {
        if (busy) return
        val base = Store.normalize(address.text.toString())
        if (base == null) { showError(getString(R.string.err_empty)); return }
        showError(null)
        busy = true
        button.isEnabled = false
        button.text = getString(R.string.connecting)
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(address.windowToken, 0)
        val pw = password.text.toString()
        thread {
            val result = probe(base, pw)
            runOnUiThread {
                busy = false
                button.isEnabled = true
                button.text = getString(R.string.connect)
                when (result) {
                    Result.OK -> {
                        store.url = base
                        store.password = pw
                        startActivity(Intent(this, MainActivity::class.java))
                        finish()
                    }
                    Result.NEED_PASSWORD -> {
                        password.visibility = android.view.View.VISIBLE
                        password.requestFocus()
                        showError(getString(if (pw.isEmpty()) R.string.err_password else R.string.err_wrong_password))
                    }
                    Result.NOT_SERVER -> showError(getString(R.string.err_notserver))
                    Result.UNREACHABLE -> showError(getString(R.string.err_unreachable))
                }
            }
        }
    }

    private enum class Result { OK, NEED_PASSWORD, NOT_SERVER, UNREACHABLE }

    private fun probe(base: String, pw: String): Result {
        return try {
            val c = URL("$base/api/state").openConnection() as HttpURLConnection
            c.connectTimeout = 5000
            c.readTimeout = 6000
            if (pw.isNotEmpty()) {
                val tok = Base64.encodeToString(":$pw".toByteArray(), Base64.NO_WRAP)
                c.setRequestProperty("Authorization", "Basic $tok")
            }
            val code = c.responseCode
            when {
                code == 401 -> Result.NEED_PASSWORD
                code in 200..299 -> {
                    val body = c.inputStream.bufferedReader().use { it.readText().take(4000) }
                    if (body.trimStart().startsWith("{")) Result.OK else Result.NOT_SERVER
                }
                else -> Result.NOT_SERVER
            }
        } catch (e: Exception) {
            Result.UNREACHABLE
        }
    }
}
