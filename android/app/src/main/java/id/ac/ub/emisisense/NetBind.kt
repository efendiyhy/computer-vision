package id.ac.ub.emisisense

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import java.net.URI

/**
 * Hotspot Orange Pi tidak punya internet, sehingga Android bisa mengalihkan lalu lintas aplikasi ke data seluler
 * dan alamat 10.42.0.1 tidak terjangkau. Untuk alamat jaringan lokal, proses aplikasi diikat ke Wi-Fi.
 */
object NetBind {
    @Volatile var wifi: Network? = null
    private var cb: ConnectivityManager.NetworkCallback? = null

    fun isPrivate(base: String): Boolean = try {
        val h = URI(base).host ?: ""
        h.startsWith("10.") || h.startsWith("192.168.") || h.startsWith("169.254.") ||
            Regex("^172\\.(1[6-9]|2\\d|3[01])\\..*").matches(h) || h.endsWith(".local")
    } catch (e: Exception) { false }

    @Synchronized
    fun apply(ctx: Context, base: String) {
        val cm = ctx.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        if (!isPrivate(base)) { release(cm); return }
        if (cb != null) return
        val req = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                wifi = network
                cm.bindProcessToNetwork(network)
            }
            override fun onLost(network: Network) {
                if (wifi == network) { wifi = null; cm.bindProcessToNetwork(null) }
            }
        }
        try {
            cm.requestNetwork(req, callback)
            cb = callback
        } catch (e: Exception) { /* tanpa izin/perangkat tidak mendukung: pakai jaringan bawaan */ }
    }

    private fun release(cm: ConnectivityManager) {
        cb?.let { runCatching { cm.unregisterNetworkCallback(it) } }
        cb = null; wifi = null
        cm.bindProcessToNetwork(null)
    }
}
