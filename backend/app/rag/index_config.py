"""
智旅云图 - 向量索引优化配置模块
提供向量索引性能优化、增量更新、备份恢复、健康检查功能
"""

import os
import json
import shutil
from pathlib import Path
from typing import Optional, Any
from datetime import datetime, timedelta

from loguru import logger

from app.config import settings
from app.rag.vector_db import vector_db_service, VectorDBService


class IndexOptimizer:
    """向量索引优化器"""

    def __init__(self, vector_db: Optional[VectorDBService] = None):
        self.vector_db = vector_db or vector_db_service
        self._index_config = self._load_index_config()

    def _load_index_config(self) -> dict:
        """加载索引配置"""
        config_path = Path(__file__).parent.parent.parent / "data" / "retrieval_rules.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return self._get_default_config()

    def _get_default_config(self) -> dict:
        """获取默认索引配置"""
        return {
            "index": {
                "optimization": {
                    "hnsw_space_type": "cosine",
                    "hnsw_ef_construction": 200,
                    "hnsw_m": 16,
                    "batch_size": 100,
                    "enable_quantization": False
                },
                "maintenance": {
                    "auto_vacuum": True,
                    "vacuum_interval_hours": 24
                }
            }
        }

    def get_index_settings(self) -> dict:
        """获取当前索引设置"""
        return {
            "dimension": self.vector_db.EMBEDDING_DIMENSION,
            "collection_name": self.vector_db.collection_name,
            "document_count": self.vector_db.count(),
            "persist_directory": self.vector_db.persist_directory,
            "optimization": self._index_config.get("index", {}).get("optimization", {}),
            "maintenance": self._index_config.get("index", {}).get("maintenance", {})
        }

    def analyze_index_performance(self) -> dict:
        """
        分析索引性能

        Returns:
            dict: 性能分析报告
        """
        try:
            count = self.vector_db.count()
            collection_info = self.vector_db.get_collection_info()

            estimated_size = self._estimate_storage_size(count)

            report = {
                "timestamp": datetime.now().isoformat(),
                "document_count": count,
                "estimated_size_mb": estimated_size,
                "collection_info": collection_info,
                "recommendations": self._generate_recommendations(count, estimated_size)
            }

            return report
        except Exception as e:
            logger.error(f"索引性能分析失败: {e}")
            return {"error": str(e)}

    def _estimate_storage_size(self, doc_count: int) -> float:
        """估算存储大小（MB）"""
        avg_vector_size = self.vector_db.EMBEDDING_DIMENSION * 4
        avg_metadata_size = 500
        avg_per_doc = avg_vector_size + avg_metadata_size
        return (doc_count * avg_per_doc) / (1024 * 1024)

    def _generate_recommendations(self, doc_count: int, size_mb: float) -> list[str]:
        """生成优化建议"""
        recommendations = []

        if doc_count == 0:
            recommendations.append("索引为空，建议执行入库脚本填充数据")
        elif doc_count < 100:
            recommendations.append("文档数量较少，检索性能应该良好")
        elif doc_count < 1000:
            recommendations.append("文档数量适中，可考虑启用 HNSW 优化")
        else:
            recommendations.append("文档数量较大，建议监控查询延迟")

        if size_mb > 500:
            recommendations.append("存储占用较大，建议定期清理过期数据")

        return recommendations

    def optimize_index(self) -> dict:
        """
        执行索引优化

        Returns:
            dict: 优化结果
        """
        logger.info("开始索引优化...")
        result = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "actions": []
        }

        try:
            count = self.vector_db.count()
            if count > 0:
                result["actions"].append({
                    "action": "analyze",
                    "message": f"索引分析完成，当前文档数: {count}"
                })

            result["actions"].append({
                "action": "optimize",
                "message": "ChromaDB 自动维护索引，无需手动优化"
            })

            logger.info("索引优化完成")
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"索引优化失败: {e}")

        return result


class IncrementalUpdateManager:
    """增量更新管理器"""

    def __init__(self, vector_db: Optional[VectorDBService] = None):
        self.vector_db = vector_db or vector_db_service
        self._state_file = Path(settings.CHROMA_DB_PATH) / ".update_state.json"
        self._state = self._load_state()

    def _load_state(self) -> dict:
        """加载更新状态"""
        if self._state_file.exists():
            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return self._get_default_state()

    def _get_default_state(self) -> dict:
        """获取默认状态"""
        return {
            "last_update": None,
            "version": "1.0",
            "cities": {}
        }

    def _save_state(self) -> None:
        """保存更新状态"""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def check_updates_needed(self, guide_dir: str) -> dict:
        """
        检查是否需要更新

        Args:
            guide_dir: 攻略文档目录

        Returns:
            dict: 检查结果
        """
        guide_path = Path(guide_dir)
        updates_needed = []

        for guide_file in guide_path.glob("*_guide.md"):
            city = guide_file.stem.replace("_guide", "")
            file_mtime = datetime.fromtimestamp(guide_file.stat().st_mtime)

            last_update = self._state.get("cities", {}).get(city, {}).get("updated_at")

            if last_update:
                last_update_dt = datetime.fromisoformat(last_update)
                if file_mtime > last_update_dt:
                    updates_needed.append({
                        "city": city,
                        "reason": "文件已更新",
                        "file_mtime": file_mtime.isoformat()
                    })
            else:
                updates_needed.append({
                    "city": city,
                    "reason": "新增城市",
                    "file_mtime": file_mtime.isoformat()
                })

        return {
            "updates_needed": len(updates_needed) > 0,
            "cities": updates_needed
        }

    def mark_updated(self, city: str) -> None:
        """标记城市已更新"""
        if "cities" not in self._state:
            self._state["cities"] = {}

        self._state["cities"][city] = {
            "updated_at": datetime.now().isoformat(),
            "version": self._state.get("version", "1.0")
        }
        self._state["last_update"] = datetime.now().isoformat()
        self._save_state()

    def get_update_status(self) -> dict:
        """获取更新状态"""
        return {
            "last_update": self._state.get("last_update"),
            "version": self._state.get("version"),
            "cities": self._state.get("cities", {})
        }


class BackupManager:
    """备份管理器"""

    def __init__(self, vector_db: Optional[VectorDBService] = None):
        self.vector_db = vector_db or vector_db_service
        self._backup_dir = Path(settings.CHROMA_DB_PATH).parent / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, name: Optional[str] = None) -> str:
        """
        创建备份

        Args:
            name: 备份名称（可选，默认使用时间戳）

        Returns:
            str: 备份路径
        """
        if name is None:
            name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        backup_path = self._backup_dir / name

        try:
            shutil.copytree(
                self.vector_db.persist_directory,
                backup_path,
                dirs_exist_ok=True
            )

            self._save_backup_metadata(backup_path, name)

            logger.info(f"备份创建成功: {backup_path}")
            return str(backup_path)
        except Exception as e:
            logger.error(f"创建备份失败: {e}")
            raise

    def list_backups(self) -> list[dict]:
        """列出所有备份"""
        backups = []

        for backup_path in self._backup_dir.iterdir():
            if backup_path.is_dir():
                metadata = self._load_backup_metadata(backup_path)
                stat = backup_path.stat()

                backups.append({
                    "name": backup_path.name,
                    "path": str(backup_path),
                    "created_at": metadata.get("created_at"),
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "doc_count": metadata.get("doc_count", 0)
                })

        return sorted(backups, key=lambda x: x.get("created_at", ""), reverse=True)

    def restore_backup(self, name: str) -> bool:
        """
        恢复备份

        Args:
            name: 备份名称

        Returns:
            bool: 是否恢复成功
        """
        backup_path = self._backup_dir / name

        if not backup_path.exists():
            logger.error(f"备份不存在: {backup_path}")
            return False

        try:
            self.vector_db.reset_collection()

            for item in os.listdir(backup_path):
                src = backup_path / item
                dst = Path(self.vector_db.persist_directory) / item

                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)

            self.vector_db._collection = None

            logger.info(f"备份恢复成功: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"恢复备份失败: {e}")
            return False

    def delete_backup(self, name: str) -> bool:
        """
        删除备份

        Args:
            name: 备份名称

        Returns:
            bool: 是否删除成功
        """
        backup_path = self._backup_dir / name

        if not backup_path.exists():
            logger.error(f"备份不存在: {backup_path}")
            return False

        try:
            shutil.rmtree(backup_path)
            logger.info(f"备份已删除: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"删除备份失败: {e}")
            return False

    def _save_backup_metadata(self, backup_path: Path, name: str) -> None:
        """保存备份元数据"""
        metadata = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "doc_count": self.vector_db.count()
        }

        metadata_file = backup_path / ".backup_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _load_backup_metadata(self, backup_path: Path) -> dict:
        """加载备份元数据"""
        metadata_file = backup_path / ".backup_metadata.json"

        if metadata_file.exists():
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        return {}


class HealthMonitor:
    """健康监控器"""

    def __init__(self, vector_db: Optional[VectorDBService] = None):
        self.vector_db = vector_db or vector_db_service
        self._metrics_history: list[dict] = []
        self._max_history = 100

    def check_health(self) -> dict:
        """
        执行健康检查

        Returns:
            dict: 健康状态报告
        """
        report = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "checks": {}
        }

        report["checks"]["connection"] = self._check_connection()
        report["checks"]["storage"] = self._check_storage()
        report["checks"]["collection"] = self._check_collection()
        report["checks"]["data_integrity"] = self._check_data_integrity()

        if any(c.get("status") != "ok" for c in report["checks"].values()):
            report["status"] = "degraded"

        if any(c.get("status") == "error" for c in report["checks"].values()):
            report["status"] = "unhealthy"

        self._record_metric(report)
        return report

    def _check_connection(self) -> dict:
        """检查连接"""
        try:
            count = self.vector_db.count()
            return {"status": "ok", "message": f"连接正常，文档数: {count}"}
        except Exception as e:
            return {"status": "error", "message": f"连接失败: {e}"}

    def _check_storage(self) -> dict:
        """检查存储"""
        try:
            persist_path = Path(self.vector_db.persist_directory)

            if not persist_path.exists():
                return {"status": "error", "message": "存储目录不存在"}

            total_size = sum(f.stat().st_size for f in persist_path.rglob("*") if f.is_file())

            return {
                "status": "ok",
                "path": str(persist_path),
                "size_mb": round(total_size / (1024 * 1024), 2)
            }
        except Exception as e:
            return {"status": "error", "message": f"存储检查失败: {e}"}

    def _check_collection(self) -> dict:
        """检查集合"""
        try:
            info = self.vector_db.get_collection_info()
            return {
                "status": "ok",
                "name": info.get("name"),
                "count": info.get("count", 0)
            }
        except Exception as e:
            return {"status": "error", "message": f"集合检查失败: {e}"}

    def _check_data_integrity(self) -> dict:
        """检查数据完整性"""
        try:
            all_data = self.vector_db.collection.get(limit=100, include=["metadatas"])

            required_fields = ["city", "category", "source_file"]
            issues = []

            for i, metadata in enumerate(all_data.get("metadatas", [])):
                if not metadata:
                    issues.append(f"ID {all_data['ids'][i]} 缺少元数据")
                    continue

                for field in required_fields:
                    if field not in metadata:
                        issues.append(f"ID {all_data['ids'][i]} 缺少字段: {field}")

            if issues:
                return {
                    "status": "warning",
                    "message": f"发现 {len(issues)} 个数据问题",
                    "issues": issues[:10]
                }

            return {"status": "ok", "message": "数据完整性检查通过"}
        except Exception as e:
            return {"status": "error", "message": f"完整性检查失败: {e}"}

    def _record_metric(self, report: dict) -> None:
        """记录指标"""
        metric = {
            "timestamp": report["timestamp"],
            "status": report["status"],
            "doc_count": report["checks"].get("collection", {}).get("count", 0)
        }

        self._metrics_history.append(metric)

        if len(self._metrics_history) > self._max_history:
            self._metrics_history = self._metrics_history[-self._max_history:]

    def get_metrics(self, hours: int = 24) -> dict:
        """
        获取历史指标

        Args:
            hours: 回溯小时数

        Returns:
            dict: 指标统计
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [
            m for m in self._metrics_history
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]

        if not recent:
            return {"message": "暂无历史数据"}

        status_counts = {}
        for m in recent:
            status = m["status"]
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "period_hours": hours,
            "total_records": len(recent),
            "status_distribution": status_counts,
            "current_status": recent[-1]["status"] if recent else "unknown",
            "doc_count": recent[-1]["doc_count"] if recent else 0
        }


index_optimizer = IndexOptimizer()
incremental_update_manager = IncrementalUpdateManager()
backup_manager = BackupManager()
health_monitor = HealthMonitor()
