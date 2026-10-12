"""
权限初始化脚本 - 阶段4知识库权限
"""

# 权限配置数据
KNOWLEDGE_PERMISSIONS = [
    {
        "resource": "knowledge",
        "action": "create",
        "description": "创建知识库",
    },
    {
        "resource": "knowledge",
        "action": "read",
        "description": "查看知识库",
    },
    {
        "resource": "knowledge",
        "action": "update",
        "description": "编辑知识库",
    },
    {
        "resource": "knowledge",
        "action": "delete",
        "description": "删除知识库",
    },
    {
        "resource": "knowledge",
        "action": "upload",
        "description": "上传文档",
    },
]


def init_knowledge_permissions(db_session):
    """初始化知识库权限"""
    from app.models import Permission, Role, role_permission

    for perm_data in KNOWLEDGE_PERMISSIONS:
        # 检查权限是否已存在
        existing = db_session.query(Permission).filter(
            Permission.resource == perm_data["resource"],
            Permission.action == perm_data["action"],
        ).first()

        if not existing:
            perm = Permission(
                resource=perm_data["resource"],
                action=perm_data["action"],
                description=perm_data["description"],
            )
            db_session.add(perm)

    db_session.commit()

    knowledge_perms = (
        db_session.query(Permission)
        .filter(Permission.resource == "knowledge")
        .all()
    )
    tenant_roles = (
        db_session.query(Role)
        .filter(
            Role.code.like("tenant_admin_%") | Role.code.like("tenant_member_%")
        )
        .all()
    )

    for role in tenant_roles:
        for perm in knowledge_perms:
            existing_binding = db_session.execute(
                role_permission.select().where(
                    role_permission.c.role_id == role.id,
                    role_permission.c.permission_id == perm.id,
                )
            ).first()
            if not existing_binding:
                db_session.execute(
                    role_permission.insert().values(
                        role_id=role.id,
                        permission_id=perm.id,
                    )
                )

    db_session.commit()


if __name__ == "__main__":
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        init_knowledge_permissions(db)
        print("Knowledge base permissions initialized successfully")
    finally:
        db.close()
