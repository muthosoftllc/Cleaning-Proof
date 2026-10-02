package app.cleaningproof.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [JobEntity::class, TaskEntity::class, IssueEntity::class, PhotoEntity::class, MutationEntity::class],
    version = 1,
    exportSchema = true
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun jobs(): JobDao
    abstract fun tasks(): TaskDao
    abstract fun issues(): IssueDao
    abstract fun photos(): PhotoDao
    abstract fun mutations(): MutationDao

    companion object {
        fun build(context: Context): AppDatabase =
            Room.databaseBuilder(context, AppDatabase::class.java, "cleaningproof.db")
                // Never fall back to destructive migration: the DB holds unsynced evidence.
                .build()
    }
}
