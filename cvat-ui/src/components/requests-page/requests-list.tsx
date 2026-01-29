// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useCallback, useMemo } from 'react';
import { shallowEqual, useDispatch, useSelector } from 'react-redux';
import dayjs from 'dayjs';
import { CombinedState, RequestsQuery, SelectedResourceType } from 'reducers';

import { Row, Col } from 'antd/lib/grid';
import Pagination from 'antd/lib/pagination';
import Button from 'antd/lib/button';
import { DownloadOutlined } from '@ant-design/icons';

import { Request, RQStatus } from 'cvat-core-wrapper';
import { requestsActions } from 'actions/requests-actions';

import dimensions from 'utils/dimensions';
import { ResourceSelectionInfo } from 'components/resource-sorting-filtering';
import BulkWrapper from 'components/bulk-wrapper';
import { selectionActions } from 'actions/selection-actions';
import RequestCard from './request-card';

interface Props {
    query: RequestsQuery;
    count: number;
}

function setUpRequestsList(requests: Request[], newPage: number, pageSize: number): Request[] {
    const displayRequests = [...requests];
    displayRequests.sort((a, b) => dayjs(b.createdDate).valueOf() - dayjs(a.createdDate).valueOf());
    return displayRequests.slice((newPage - 1) * pageSize, newPage * pageSize);
}

function RequestsList(props: Readonly<Props>): JSX.Element {
    const dispatch = useDispatch();
    const { query, count } = props;
    const { page, pageSize } = query;
    const { requests, cancelled, selectedCount, selectedIds } = useSelector((state: CombinedState) => ({
        requests: state.requests.requests,
        cancelled: state.requests.cancelled,
        selectedCount: state.requests.selected.length,
        selectedIds: state.requests.selected,
    }), shallowEqual);

    const requestList = Object.values(requests);
    const requestViews = setUpRequestsList(requestList, page, pageSize);
    const requestIds = requestViews.map((request) => request.id).filter((id) => !cancelled[id]);
    const onSelectAll = useCallback(() => {
        dispatch(selectionActions.selectResources(requestIds, SelectedResourceType.REQUESTS));
    }, [requestIds]);

    // Filter all downloadable requests (finished with URL, not cancelled)
    const allDownloadableRequests = useMemo(() => requestList.filter((request: Request) => (
        request.status === RQStatus.FINISHED &&
            !!request.url &&
            !cancelled[request.id]
    )), [requestList, cancelled]);

    // Filter selected downloadable requests
    const selectedDownloadableRequests = useMemo(() => {
        if (selectedIds.length === 0) return [];
        return allDownloadableRequests.filter((request) => selectedIds.includes(request.id));
    }, [allDownloadableRequests, selectedIds]);

    // Only download selected items (no "download all" when nothing selected)
    const hasSelection = selectedIds.length > 0;
    const downloadableCount = selectedDownloadableRequests.length;

    // Download handler (selected only)
    const onDownload = useCallback(() => {
        if (downloadableCount === 0) return;

        selectedDownloadableRequests.forEach((request) => {
            const downloadAnchor = window.document.getElementById('downloadAnchor') as HTMLAnchorElement | null;
            if (downloadAnchor && request.url) {
                downloadAnchor.href = request.url;
                downloadAnchor.click();
            }
        });
    }, [selectedDownloadableRequests, downloadableCount]);

    // Button label: "Download" when nothing selected, "Download (N)" when selected
    const downloadButtonLabel = hasSelection ? `Download (${downloadableCount})` : 'Download';

    return (
        <>
            <Row justify='center'>
                <Col {...dimensions}>
                    <Row justify='space-between' align='middle' className='cvat-requests-header-row'>
                        <Col>
                            <ResourceSelectionInfo selectedCount={selectedCount} onSelectAll={onSelectAll} />
                        </Col>
                        <Col>
                            <Button
                                className='cvat-requests-download-button'
                                type='primary'
                                icon={<DownloadOutlined />}
                                disabled={!hasSelection || downloadableCount === 0}
                                onClick={onDownload}
                            >
                                {downloadButtonLabel}
                            </Button>
                        </Col>
                    </Row>
                </Col>
            </Row>
            <Row justify='center' className='cvat-resource-list-wrapper'>
                <Col className='cvat-requests-list' {...dimensions}>
                    <BulkWrapper currentResourceIds={requestIds} resourceType={SelectedResourceType.REQUESTS}>
                        {(selectProps) => (
                            requestViews.map((request: Request) => {
                                const isCancelled = request.id in cancelled;
                                const selectableIndex = isCancelled ? -1 : requestIds.indexOf(request.id);
                                const canSelect = !isCancelled && selectableIndex !== -1;

                                const { selected, onClick } = canSelect ?
                                    selectProps(request.id, selectableIndex) :
                                    { selected: false, onClick: () => false };

                                return (
                                    <RequestCard
                                        request={request}
                                        key={request.id}
                                        cancelled={isCancelled}
                                        selected={selected}
                                        onClick={onClick}
                                    />
                                );
                            })
                        )}
                    </BulkWrapper>
                </Col>
            </Row>
            <Row justify='center' align='middle' className='cvat-resource-pagination-wrapper'>
                <Pagination
                    className='cvat-tasks-pagination'
                    onChange={(newPage: number, newPageSize: number) => {
                        dispatch(requestsActions.getRequests({
                            ...query,
                            page: newPage,
                            pageSize: newPageSize,
                        }, false));
                    }}
                    total={count}
                    current={page}
                    pageSize={pageSize}
                    showQuickJumper
                    showSizeChanger
                />
            </Row>
        </>
    );
}

export default React.memo(RequestsList);
