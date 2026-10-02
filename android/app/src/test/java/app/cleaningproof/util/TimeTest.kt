package app.cleaningproof.util

import org.junit.Assert.assertEquals
import org.junit.Test

class TimeTest {
    @Test
    fun parsesDjangoUtcOffset() {
        assertEquals(1_759_392_000_000L, "2025-10-02T08:00:00+00:00".isoToMillis())
    }

    @Test
    fun parsesNonUtcOffsetAndFractions() {
        assertEquals(1_759_392_000_123L, "2025-10-02T09:00:00.123+01:00".isoToMillis())
    }

    @Test
    fun roundTrips() {
        val now = 1_759_392_000_456L
        assertEquals(now, now.toIso().isoToMillis())
    }
}
