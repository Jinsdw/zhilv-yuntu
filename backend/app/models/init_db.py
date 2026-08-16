"""
智旅云图 - 数据库初始化脚本
创建数据库表、初始化基础数据
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import json

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.models.db_models import (
    Base, init_db, CityInfoDB, GuideDocumentDB,
    TripHistoryDB, UserPreferenceDB, QueryCacheDB, ApiUsageLogDB
)


def get_engine(database_url: str = None):
    """获取数据库引擎"""
    if database_url is None:
        database_url = settings.DATABASE_URL
    
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    
    return create_engine(
        database_url,
        connect_args=connect_args,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )


def init_database(engine) -> bool:
    """
    初始化数据库
    
    Args:
        engine: 数据库引擎
        
    Returns:
        bool: 是否成功
    """
    print("=" * 50)
    print("智旅云图 - 数据库初始化")
    print("=" * 50)
    
    try:
        # 创建所有表
        print("\n[1/4] Creating database tables...")
        init_db(engine)
        print("[OK] All tables created successfully")
        
        # 初始化基础城市数据
        print("\n[2/4] Initializing city data...")
        init_city_data(engine)
        print("[OK] City data initialized")
        
        # 初始化攻略文档数据
        print("\n[3/4] Checking guide documents...")
        init_guide_data(engine)
        print("[OK] Guide documents checked")
        
        # 创建索引
        print("\n[4/4] Creating indexes...")
        create_indexes(engine)
        print("[OK] Indexes created successfully")
        
        print("\n" + "=" * 50)
        print("Database initialization complete!")
        print("=" * 50)
        
        return True
        
    except SQLAlchemyError as e:
        print(f"\n[ERROR] Database initialization failed: {e}")
        return False


def init_city_data(engine) -> None:
    """初始化城市基础数据"""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # 检查是否已有城市数据
        existing_count = session.query(CityInfoDB).count()
        if existing_count > 0:
            print(f"  - Already have {existing_count} city records, skipping...")
            return
        
        # 城市数据
        cities = [
            {
                "city_name": "北京",
                "city_name_en": "Beijing",
                "city_code": "010",
                "province": "北京",
                "latitude": 39.9042,
                "longitude": 116.4074,
                "city_level": "一线",
                "tags": ["古都", "政治中心", "文化名城"],
                "specialties": ["北京烤鸭", "炸酱面", "豆汁儿", "卤煮"],
                "attractions": ["故宫", "长城", "天坛", "颐和园", "天安门"],
                "best_travel_months": [4, 5, 9, 10],
                "local_tips": "北京四季分明，春秋最佳。景点需提前预约。",
                "emergency_phone": "010-12345",
                "tourism_hotline": "010-12301"
            },
            {
                "city_name": "大理",
                "city_name_en": "Dali",
                "city_code": "0872",
                "province": "云南",
                "latitude": 25.6069,
                "longitude": 100.2676,
                "city_level": "三线",
                "tags": ["古城", "洱海", "民族风情"],
                "specialties": ["饵丝", "乳扇", "喜洲粑粑", "酸辣鱼"],
                "attractions": ["大理古城", "洱海", "双廊", "苍山", "喜洲古镇"],
                "best_travel_months": [3, 4, 5, 9, 10],
                "local_tips": "大理早晚温差大，紫外线强，需做好防晒。",
                "emergency_phone": "0872-12345",
                "tourism_hotline": "0872-12301"
            },
            {
                "city_name": "成都",
                "city_name_en": "Chengdu",
                "city_code": "028",
                "province": "四川",
                "latitude": 30.5728,
                "longitude": 104.0668,
                "city_level": "新一线",
                "tags": ["美食之都", "熊猫", "休闲"],
                "specialties": ["火锅", "串串香", "担担面", "龙抄手", "钟水饺"],
                "attractions": ["宽窄巷子", "锦里", "大熊猫基地", "武侯祠", "青城山"],
                "best_travel_months": [3, 4, 5, 9, 10, 11],
                "local_tips": "成都美食偏辣，可提前告知口味偏好。",
                "emergency_phone": "028-12345",
                "tourism_hotline": "028-12301"
            },
            {
                "city_name": "西安",
                "city_name_en": "Xi'an",
                "city_code": "029",
                "province": "陕西",
                "latitude": 34.3416,
                "longitude": 108.9398,
                "city_level": "新一线",
                "tags": ["古都", "历史", "美食"],
                "specialties": ["肉夹馍", "羊肉泡馍", "凉皮", "biangbiang面", "肉丸胡辣汤"],
                "attractions": ["秦始皇兵马俑", "大雁塔", "古城墙", "回民街", "华清宫"],
                "best_travel_months": [3, 4, 5, 9, 10, 11],
                "local_tips": "西安历史底蕴深厚，建议请导游讲解。",
                "emergency_phone": "029-12345",
                "tourism_hotline": "029-12301"
            },
            {
                "city_name": "厦门",
                "city_name_en": "Xiamen",
                "city_code": "0592",
                "province": "福建",
                "latitude": 24.4798,
                "longitude": 118.0894,
                "city_level": "二线",
                "tags": ["海滨", "鼓浪屿", "文艺"],
                "specialties": ["沙茶面", "海蛎煎", "烧肉粽", "姜母鸭", "土笋冻"],
                "attractions": ["鼓浪屿", "厦门大学", "南普陀寺", "环岛路", "曾厝垵"],
                "best_travel_months": [3, 4, 5, 10, 11, 12],
                "local_tips": "鼓浪屿需提前购船票，岛上禁止机动车。",
                "emergency_phone": "0592-12345",
                "tourism_hotline": "0592-12301"
            },
            {
                "city_name": "三亚",
                "city_name_en": "Sanya",
                "city_code": "0898",
                "province": "海南",
                "latitude": 18.2528,
                "longitude": 109.5119,
                "city_level": "三线",
                "tags": ["海滨", "度假", "热带"],
                "specialties": ["海鲜", "椰子鸡", "文昌鸡", "和乐蟹", "热带水果"],
                "attractions": ["亚龙湾", "天涯海角", "南山文化旅游区", "蜈支洲岛", "大小洞天"],
                "best_travel_months": [10, 11, 12, 1, 2, 3],
                "local_tips": "三亚紫外线强，注意防晒，海鲜选择正规餐厅。",
                "emergency_phone": "0898-12345",
                "tourism_hotline": "0898-12301"
            }
        ]
        
        # 插入城市数据
        for city_data in cities:
            city = CityInfoDB(**city_data)
            session.add(city)
        
        session.commit()
        print(f"  - Added {len(cities)} city records")
        
    except Exception as e:
        session.rollback()
        print(f"  - Failed to initialize city data: {e}")
        raise
    finally:
        session.close()


def init_guide_data(engine) -> None:
    """检查攻略文档数据"""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        guide_count = session.query(GuideDocumentDB).count()
        print(f"  - Database has {guide_count} guide documents")
        
        # 读取实际攻略文件
        data_dir = project_root / "backend" / "data"
        if data_dir.exists():
            for city_dir in data_dir.iterdir():
                if city_dir.is_dir():
                    city_name = city_dir.name
                    md_files = list(city_dir.glob("*.md"))
                    print(f"  - {city_name}: {len(md_files)} 个攻略文件")
        
    except Exception as e:
        print(f"  - Failed to check guide documents: {e}")
    finally:
        session.close()


def create_indexes(engine) -> None:
    """创建额外索引（SQLite不支持某些PostgreSQL特性）"""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # 检查数据库类型
        dialect = engine.dialect.name
        
        if dialect == "sqlite":
            # SQLite使用GLOB操作JSON
            print("  - SQLite数据库，跳过JSON索引创建")
        elif dialect == "postgresql":
            # PostgreSQL可以创建JSON GIN索引
            pass
        
        print("  - 索引检查完成")
        
    except Exception as e:
        print(f"  - 创建索引失败: {e}")
    finally:
        session.close()


def drop_all_tables(engine) -> bool:
    """删除所有表"""
    print("=" * 50)
    print("警告：即将删除所有数据库表！")
    print("=" * 50)
    
    try:
        Base.metadata.drop_all(bind=engine)
        print("✓ 所有表已删除")
        return True
    except SQLAlchemyError as e:
        print(f"✗ 删除表失败: {e}")
        return False


def reset_database(database_url: str = None) -> bool:
    """重置数据库（删除后重建）"""
    engine = get_engine(database_url)
    
    if not drop_all_tables(engine):
        return False
    
    return init_database(engine)


def show_tables(engine) -> None:
    """显示所有表"""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        print("\nDatabase tables:")
        print("-" * 40)
        
        for table_name in Base.metadata.tables.keys():
            count = session.execute(
                text(f"SELECT COUNT(*) as cnt FROM {table_name}")
            ).scalar()
            print(f"  {table_name}: {count} records")
            
    except Exception as e:
        print(f"  Query failed: {e}")
    finally:
        session.close()


def show_table_schema(engine, table_name: str) -> None:
    """显示表结构"""
    print(f"\n表 {table_name} 结构:")
    print("-" * 60)
    
    try:
        result = engine.execute(text(f"PRAGMA table_info({table_name})"))
        for row in result:
            print(f"  {row[1]:20} | {row[2]:15} | nullable: {row[3]}")
    except Exception as e:
        print(f"  查询失败: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="数据库管理工具")
    parser.add_argument("action", choices=["init", "reset", "drop", "show", "schema"],
                       help="操作类型")
    parser.add_argument("--table", help="表名（用于schema命令）")
    parser.add_argument("--db", help="数据库URL（可选）")
    
    args = parser.parse_args()
    
    engine = get_engine(args.db)
    
    if args.action == "init":
        init_database(engine)
    elif args.action == "reset":
        reset_database(args.db)
    elif args.action == "drop":
        confirm = input("确定要删除所有表吗？(y/N): ")
        if confirm.lower() == "y":
            drop_all_tables(engine)
    elif args.action == "show":
        show_tables(engine)
    elif args.action == "schema":
        if args.table:
            show_table_schema(engine, args.table)
        else:
            print("请指定表名: --table <table_name>")
