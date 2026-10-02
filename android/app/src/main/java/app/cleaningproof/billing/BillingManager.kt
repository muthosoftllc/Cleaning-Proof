package app.cleaningproof.billing

import android.app.Activity
import android.content.Context
import app.cleaningproof.data.remote.ApiService
import app.cleaningproof.data.remote.BillingStatusDto
import app.cleaningproof.data.remote.SessionStore
import app.cleaningproof.data.remote.VerifyPurchaseRequest
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.PurchasesUpdatedListener
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.android.billingclient.api.queryProductDetails
import com.android.billingclient.api.queryPurchasesAsync
import kotlin.coroutines.resume
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * Google Play Billing. The app never grants entitlements itself: every
 * purchase token goes to the backend, which verifies it with Google,
 * acknowledges it and returns the organization's plan.
 */
class BillingManager(
    context: Context,
    private val api: ApiService,
    private val session: SessionStore
) : PurchasesUpdatedListener {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _status = MutableStateFlow<BillingStatusDto?>(null)
    val status: StateFlow<BillingStatusDto?> = _status

    private val client = BillingClient.newBuilder(context)
        .setListener(this)
        .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
        .build()

    private suspend fun connect(): Boolean {
        if (client.isReady) return true
        return suspendCancellableCoroutine { cont ->
            client.startConnection(object : BillingClientStateListener {
                override fun onBillingSetupFinished(result: BillingResult) {
                    if (cont.isActive) cont.resume(result.responseCode == BillingClient.BillingResponseCode.OK)
                }

                override fun onBillingServiceDisconnected() {
                    if (cont.isActive) cont.resume(false)
                }
            })
        }
    }

    suspend fun refreshStatus() {
        _status.value = runCatching { api.billing() }.getOrNull() ?: _status.value
    }

    suspend fun products(ids: List<String> = PRODUCT_IDS): List<ProductDetails> {
        if (!connect()) return emptyList()
        val params = QueryProductDetailsParams.newBuilder().setProductList(
            ids.map {
                QueryProductDetailsParams.Product.newBuilder()
                    .setProductId(it)
                    .setProductType(BillingClient.ProductType.SUBS)
                    .build()
            }
        ).build()
        return client.queryProductDetails(params).productDetailsList.orEmpty()
    }

    fun launchPurchase(activity: Activity, product: ProductDetails) {
        val offer = product.subscriptionOfferDetails?.firstOrNull() ?: return
        val orgId = session.organizationId ?: return
        val params = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(
                listOf(
                    BillingFlowParams.ProductDetailsParams.newBuilder()
                        .setProductDetails(product)
                        .setOfferToken(offer.offerToken)
                        .build()
                )
            )
            // The backend checks this to bind the purchase to the right organization.
            .setObfuscatedAccountId(orgId)
            .build()
        client.launchBillingFlow(activity, params)
    }

    override fun onPurchasesUpdated(result: BillingResult, purchases: MutableList<Purchase>?) {
        if (result.responseCode != BillingClient.BillingResponseCode.OK) return
        purchases.orEmpty().forEach { scope.launch { verify(it) } }
    }

    /** Re-send any owned purchases (e.g. verification failed while offline). */
    suspend fun restore() {
        if (!connect()) return
        val params = QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.SUBS).build()
        client.queryPurchasesAsync(params).purchasesList.forEach { verify(it) }
    }

    private suspend fun verify(purchase: Purchase) {
        if (purchase.purchaseState != Purchase.PurchaseState.PURCHASED) return
        val productId = purchase.products.firstOrNull() ?: return
        runCatching { api.verifyPurchase(VerifyPurchaseRequest(productId, purchase.purchaseToken)) }
            .onSuccess { _status.value = it }
    }

    companion object {
        val PRODUCT_IDS = listOf("cleaningproof_pro", "cleaningproof_business")
    }
}
