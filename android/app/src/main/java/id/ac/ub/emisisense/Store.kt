package id.ac.ub.emisisense

import android.content.Context
import java.net.URI

/** Penyimpanan alamat server dan kata sandi, serta perapian alamat yang diketik pengguna. */
class Store(ctx: Context) {
    private val sp = ctx.getSharedPreferences("emisisense", Context.MODE_PRIVATE)

    var url: String
        get() = sp.getString("url", "") ?: ""
        set(v) = sp.edit().putString("url", v).apply()

    var password: String
        get() = sp.getString("pw", "") ?: ""
        set(v) = sp.edit().putString("pw", v).apply()

    companion object {
        /** "192.168.1.20", "192.168.1.20:8080", "http://host/" -> "http://host:port"; null bila tidak valid. */
        fun normalize(raw: String): String? {
            var s = raw.trim()
            if (s.isEmpty()) return null
            if (!s.contains("://")) s = "http://$s"
            return try {
                val u = URI(s)
                val host = u.host ?: return null
                val scheme = if (u.scheme == "https") "https" else "http"
                val port = if (u.port > 0) u.port else if (scheme == "https") 443 else 5000
                if (scheme == "https" && port == 443) "https://$host" else "$scheme://$host:$port"
            } catch (e: Exception) {
                null
            }
        }
    }
}
