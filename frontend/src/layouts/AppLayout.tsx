import {
  CompassOutlined,
  FileTextOutlined,
  HistoryOutlined,
  MoonOutlined,
  RocketOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { Button, Flex, Layout, Menu, Typography, theme } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'
import { layout as layoutTokens } from '@/theme'
import { useThemeMode } from '@/theme/ThemeContext'

const { Header, Content, Footer } = Layout

const MENU_ITEMS = [
  { key: ROUTES.home, icon: <CompassOutlined />, label: '规划行程' },
  { key: ROUTES.result, icon: <FileTextOutlined />, label: '行程结果' },
  { key: ROUTES.history, icon: <HistoryOutlined />, label: '历史记录' },
]

/**
 * 应用外壳：顶部导航（品牌 + 菜单 + 明暗开关）+ 内容区 + 页脚。
 * 页面只负责自身内容，通过 <Outlet /> 注入。
 */
export default function AppLayout() {
  const { dark, toggle } = useThemeMode()
  const navigate = useNavigate()
  const location = useLocation()
  const { token } = theme.useToken()

  const selectedKey =
    MENU_ITEMS.find((item) => location.pathname.startsWith(item.key))?.key ?? ROUTES.home

  return (
    <Layout style={{ minHeight: '100dvh' }}>
      {/* 顶部导航 */}
      <Header
        className="zl-topnav"
        style={{
          height: layoutTokens.headerHeight,
          paddingInline: 24,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
        }}
      >
        {/* 品牌区 */}
        <Flex align="center" gap={12} style={{ flexShrink: 0 }} onClick={() => navigate(ROUTES.home)}>
          <Flex
            align="center"
            justify="center"
            style={{
              width: 36,
              height: 36,
              borderRadius: 12,
              background: `linear-gradient(135deg, ${token.colorPrimary}, #E8A33D)`,
              color: '#fff',
              fontSize: 18,
              flexShrink: 0,
              boxShadow: '0 4px 10px rgba(192,71,47,0.28)',
            }}
          >
            <RocketOutlined />
          </Flex>
          <Flex vertical style={{ lineHeight: 1.25, cursor: 'pointer' }}>
            <Typography.Text strong className="zl-serif" style={{ fontSize: 17 }}>
              智旅云图
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              山海拾光 · AI 行程规划
            </Typography.Text>
          </Flex>
        </Flex>

        {/* 导航菜单：小屏可横向滚动 */}
        <Flex style={{ flex: 1, minWidth: 0, justifyContent: 'center',  }}>
          <Menu
            mode="horizontal"
            items={MENU_ITEMS}
            selectedKeys={[selectedKey]}
            onClick={({ key }) => navigate(key)}
            style={{
              minWidth: 420,
              background: 'transparent',
              borderBottom: 'none',
              justifyContent: 'center',
            }}
          />
        </Flex>

        {/* 明暗开关 */}
        <Button
          type="text"
          aria-label={dark ? '切换到浅色模式' : '切换到深色模式'}
          icon={dark ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggle}
          style={{ flexShrink: 0, fontSize: 16 }}
        />
      </Header>

      <Content style={{ padding: 28, paddingTop: 24 }}>
        <div
          className="zl-page"
          style={{
            maxWidth: layoutTokens.contentMaxWidth,
            margin: '0 auto',
            width: '100%',
          }}
        >
          <Outlet />
        </div>
      </Content>

      <Footer
        style={{
          textAlign: 'center',
          fontSize: 12,
          color: token.colorTextSecondary,
          paddingBlock: 18,
        }}
      >
        智旅云图 · 多 Agent 协同的智能旅游行程规划助手 · 把想去的远方，排成一天天的好日子
      </Footer>
    </Layout>
  )
}
