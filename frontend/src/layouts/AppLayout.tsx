import { useState } from 'react'

import {
  CloudOutlined,
  CompassOutlined,
  FileTextOutlined,
  HistoryOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { Avatar, Button, Flex, Layout, Menu, Switch, Typography, theme } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'
import { layout as layoutTokens } from '@/theme'
import { useThemeMode } from '@/theme/ThemeContext'

const { Header, Sider, Content, Footer } = Layout

const MENU_ITEMS = [
  { key: ROUTES.home, icon: <CompassOutlined />, label: '规划行程' },
  { key: ROUTES.result, icon: <FileTextOutlined />, label: '行程结果' },
  { key: ROUTES.history, icon: <HistoryOutlined />, label: '历史记录' },
]

/**
 * 应用外壳：侧边导航 + 顶栏（折叠 / 深色开关）+ 内容区 + 页脚。
 * 页面只负责自身内容，通过 <Outlet /> 注入。
 */
export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const { dark, toggle } = useThemeMode()
  const navigate = useNavigate()
  const location = useLocation()
  const { token } = theme.useToken()

  const selectedKey =
    MENU_ITEMS.find((item) => location.pathname.startsWith(item.key))?.key ?? ROUTES.home

  return (
    <Layout style={{ minHeight: '100dvh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        trigger={null}
        breakpoint="lg"
        onBreakpoint={setCollapsed}
        width={layoutTokens.siderWidth}
        collapsedWidth={layoutTokens.siderCollapsedWidth}
        style={{
          background: token.colorBgContainer,
          borderRight: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        {/* 品牌区 */}
        <Flex
          align="center"
          gap={10}
          style={{ padding: collapsed ? '16px 14px' : '16px 20px' }}
        >
          <Avatar
            shape="square"
            size={34}
            icon={<CloudOutlined />}
            style={{ background: token.colorPrimary, flexShrink: 0 }}
          />
          {!collapsed && (
            <Flex vertical style={{ lineHeight: 1.3 }}>
              <Typography.Text strong>智旅云图</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                AI 行程规划
              </Typography.Text>
            </Flex>
          )}
        </Flex>

        <Menu
          mode="inline"
          items={MENU_ITEMS}
          selectedKeys={[selectedKey]}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            height: 56,
            paddingInline: 16,
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Button
            type="text"
            aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed((v) => !v)}
          />

          <Flex align="center" gap={8}>
            <Switch
              checked={dark}
              onChange={toggle}
              checkedChildren={<MoonOutlined />}
              unCheckedChildren={<SunOutlined />}
              aria-label="切换深浅色模式"
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {dark ? '深色' : '浅色'}
            </Typography.Text>
          </Flex>
        </Header>

        <Content style={{ padding: 24 }}>
          <div
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
            paddingBlock: 16,
          }}
        >
          智旅云图 · 多 Agent 协同的智能旅游行程规划助手
        </Footer>
      </Layout>
    </Layout>
  )
}