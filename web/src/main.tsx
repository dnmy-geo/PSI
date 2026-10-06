import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BrowserRouter } from 'react-router-dom';
import { Root } from './root';
import './styles/index.css';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000 } } });

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={{
      token: {
        colorPrimary: '#1668dc', colorInfo: '#1668dc', colorLink: '#1668dc',
        colorText: '#202733', colorTextSecondary: '#687384', colorBgLayout: '#f4f6f8',
        colorBorder: '#dce2e9', colorBorderSecondary: '#e9edf2',
        borderRadius: 9, controlHeight: 36, fontSize: 14,
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
      },
      components: {
        Button: { primaryShadow: 'none', defaultShadow: 'none', borderRadius: 9 },
        Card: { borderRadiusLG: 14 },
        Table: { headerBg: '#f8f9fb', headerColor: '#667285', rowHoverBg: '#f2f6fd' },
        Modal: { borderRadiusLG: 16 },
      },
    }}>
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter><Root /></BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
