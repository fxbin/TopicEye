from fastapi import APIRouter, Depends
from app.api.v1.sources import router as sources_router
from app.api.v1.contents import router as contents_router
from app.api.v1.topics import router as topics_router
from app.api.v1.analyses import router as analyses_router
from app.api.v1.daily_reports import router as daily_reports_router
from app.api.v1.trends import router as trends_router
from app.api.v1.creation import router as creation_router
from app.api.v1.settings import router as settings_router
from app.api.v1.categories import router as categories_router
from app.api.v1.stats import router as stats_router
from app.api.v1.stats_jobs import router as stats_jobs_router
from app.api.v1.sources_health import router as sources_health_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.product_feedback import router as product_feedback_router
from app.api.v1.weekly_digests import router as weekly_digests_router
from app.api.v1.monthly_digests import router as monthly_digests_router
from app.api.v1.trending import router as trending_router
from app.api.v1.mother_topics import router as mother_topics_router
from app.api.v1.fanqie import router as fanqie_router
from app.api.v1.qimao import router as qimao_router
from app.api.v1.zhihu import router as zhihu_router
from app.api.v1.webnovel_reports import router as webnovel_reports_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.scheduler import router as scheduler_router
from app.api.v1.llm_models import router as llm_models_router
from app.api.v1.llm_evaluations import router as llm_evaluations_router
from app.api.v1.favorites import router as favorites_router
from app.api.v1.auth import router as auth_router
from app.api.v1.oauth import router as oauth_router
from app.api.v1.user_api_tokens import router as user_api_tokens_router
from app.api.v1.plans import router as plans_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.scoring import router as scoring_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(oauth_router)
router.include_router(user_api_tokens_router)
router.include_router(plans_router)
router.include_router(integrations_router)
router.include_router(scoring_router)
router.include_router(sources_router)
router.include_router(contents_router)
router.include_router(topics_router)
router.include_router(analyses_router)
router.include_router(daily_reports_router)
router.include_router(trends_router)
router.include_router(creation_router)
router.include_router(settings_router)
router.include_router(categories_router)
router.include_router(stats_router)
router.include_router(stats_jobs_router)
router.include_router(sources_health_router)
router.include_router(metrics_router)
router.include_router(feedback_router)
router.include_router(product_feedback_router)
router.include_router(weekly_digests_router)
router.include_router(monthly_digests_router)
router.include_router(trending_router)
router.include_router(mother_topics_router)
# 网文路由：永远注册，由 require_feature 依赖在请求时查 DB flag 守卫
from app.api.v1._feature_guard import require_feature  # noqa: E402

router.include_router(fanqie_router, dependencies=[Depends(require_feature("webnovel_module"))])
router.include_router(qimao_router, dependencies=[Depends(require_feature("webnovel_module"))])
router.include_router(zhihu_router, dependencies=[Depends(require_feature("webnovel_module"))])
router.include_router(webnovel_reports_router, dependencies=[Depends(require_feature("webnovel_module"))])
router.include_router(notifications_router)
router.include_router(scheduler_router)
router.include_router(llm_models_router)
router.include_router(llm_evaluations_router)
router.include_router(favorites_router)
